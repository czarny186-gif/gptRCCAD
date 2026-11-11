"""Kolor (zakładka Edycja): kolorowanie brył, kolor domyślny, zapis w projekcie, import w folderze i w kolorach."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen' if not os.environ.get('DISPLAY') and os.name != 'nt' else '')
os.environ['RCCAD_CONFIG_DIR'] = tempfile.mkdtemp(prefix='rccad-cfg-')
os.environ.setdefault('RCCAD_WORKERS', '0')

import cadquery as cq
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from rccad import colors as pal
from rccad import history as hist
from rccad import kernel as k
from rccad.document import Body, Document
from rccad.studio import TABS, StudioWindow
from rccad.viewport import SOLID_COLOR

RED, BLUE = pal.palette_rgb(0), pal.palette_rgb(7)


class ColorDataTests(unittest.TestCase):
    def test_colors_and_default_survive_saving_the_project(self):
        doc = Document()
        a, b = Body('A', k.box(10, 10, 10)), Body('B', k.box(5, 5, 5))
        doc.commit([a, b])
        doc.pending_op = dict(type='color', colors={a.id: list(RED)})
        doc.commit([hist.run_color(doc.bodies, doc.pending_op)][0])
        doc.set_default_color(BLUE)
        self.assertTrue(doc.dirty)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'kolory.rccadx'
            doc.save(path)
            opened = Document.load(path)
        self.assertEqual(opened.get(a.id).color, tuple(round(c, 4) for c in RED))
        self.assertIsNone(opened.get(b.id).color)
        self.assertEqual(opened.default_color, tuple(round(c, 4) for c in BLUE))
        opened.undo()
        self.assertIsNone(opened.get(a.id).color)                 # kolor to zwykły krok historii

    def test_color_survives_operations_on_the_body(self):
        body = Body('A', k.box(10, 10, 10), color=RED).prepared()
        tool = Body('B', k.box(4, 4, 30)).prepared()
        out = hist.run_bool([body, tool], dict(type='bool', op='subtract', base=body.id, tools=[tool.id]))
        self.assertEqual(next(b for b in out if b.id == body.id).color, RED)
        moved = hist.run_recipe([body], dict(type='transform', id=body.id, mode='move', v=(5, 0, 0)))
        self.assertEqual(moved[0].color, RED)

    def test_import_puts_many_parts_in_one_folder_with_different_colors(self):
        parts = [Body(f'P{i}', k.box(1, 1, 1)) for i in range(20)] + [Body('S', k.sketch('circle', 'XY', 2), 'sketch')]
        out = pal.imported(parts, 'Model')
        self.assertTrue(all(b.folder == 'Model' for b in out))
        solids = [b.color for b in out if b.kind == 'solid']
        self.assertEqual(len(set(solids[:16])), 16)               # 16 różnych kolorów, potem powtórki
        self.assertEqual(solids[16], solids[0])
        self.assertIsNone(out[-1].color)                          # szkic bez koloru
        single = pal.imported([Body('Jedna', k.box(1, 1, 1))], 'Model')
        self.assertEqual(single[0].folder, '')
        self.assertIsNone(single[0].color)

    def test_step_import_with_many_solids(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'zestaw.step'
            k.export_shapes([k.box(5, 5, 5).translate(cq.Vector(10 * i, 0, 0)) for i in range(3)], path)
            from rccad import library
            bodies = library.load_bodies('object', path)
        self.assertEqual(len(bodies), 3)
        self.assertEqual({b.folder for b in bodies}, {'zestaw'})
        self.assertEqual(len({b.color for b in bodies}), 3)


class ColorToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = StudioWindow()
        self.w.resize(1400, 850)
        self.w.show()
        self.app.processEvents()
        self.patches = [patch.object(QMessageBox, 'warning', return_value=QMessageBox.Ok),
                        patch.object(QMessageBox, 'information', return_value=QMessageBox.Ok)]
        for p in self.patches:
            p.start()
        self.a = Body('A', k.box(10, 10, 10)).prepared()
        self.b = Body('B', k.box(5, 5, 5).translate(cq.Vector(20, 0, 0))).prepared()
        self.w.document.commit([self.a, self.b])
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
        for p in self.patches:
            p.stop()

    def click_body(self, body):
        with patch.object(self.w.view, 'pick_body', return_value=body.id):
            self.w.view_clicked(10, 10, False, False)

    def test_tool_is_in_the_edit_tab(self):
        self.assertIn('color', TABS['Edycja'])
        self.w.tools['color'].click()
        self.assertEqual(self.w.mode, 'color')
        self.assertTrue(self.w.color_panel.isVisible())
        self.assertEqual(len(self.w.co_swatches), 16)

    def test_clicked_bodies_change_color_only_after_save(self):
        w = self.w
        w.set_mode('color')
        self.click_body(self.a)                               # bez wybranego koloru nic się nie dzieje
        self.assertFalse(w.co_pending)
        w.co_swatches[0].click()
        self.click_body(self.a)
        self.assertEqual(w.view.tints[self.a.id][:3], RED)    # podgląd od razu
        self.assertIsNone(w.document.get(self.a.id).color)    # ale jeszcze nie w projekcie
        w.co_swatches[7].click()
        self.click_body(self.b)
        self.assertTrue(w.co_save.isEnabled())
        steps = w.document.history_length
        w.co_save.click()
        self.assertEqual(w.document.get(self.a.id).color, tuple(round(c, 4) for c in RED))
        self.assertEqual(w.document.get(self.b.id).color, tuple(round(c, 4) for c in BLUE))
        self.assertEqual(w.document.history_length, steps + 1)
        self.assertEqual(w.document.info['op']['type'], 'color')
        self.assertEqual(w.mode, 'color')                     # okno zostaje otwarte - można kolorować dalej
        self.assertEqual(w.view.solid_rgba(w.document.get(self.a.id))[:3], tuple(round(c, 4) for c in RED))

    def test_closing_without_save_discards_colors(self):
        w = self.w
        w.set_mode('color')
        w.co_swatches[3].click()
        self.click_body(self.a)
        w.set_mode(None)
        self.assertIsNone(w.document.get(self.a.id).color)
        self.assertFalse(w.view.tints)
        self.click_body(self.b)                               # po zamknięciu okna kliknięcie już nie koloruje
        self.assertIsNone(w.document.get(self.b.id).color)

    def test_default_color_for_bodies_without_own_color(self):
        w = self.w
        w.set_mode('color')
        w.co_swatches[0].click()
        self.click_body(self.a)
        w._co_set_default(BLUE)
        self.assertEqual(w.view.default_color, BLUE)          # podgląd
        self.assertIsNone(w.document.default_color)
        w.apply_color()
        self.assertEqual(w.document.default_color, BLUE)
        self.assertEqual(w.view.solid_rgba(w.document.get(self.b.id))[:3], BLUE)
        self.assertEqual(w.view.solid_rgba(w.document.get(self.a.id))[:3], tuple(round(c, 4) for c in RED))
        new = Body('Nowa', k.box(2, 2, 2)).prepared()
        w.document.commit([*w.document.bodies, new])
        w.refresh()
        self.assertEqual(w.view.solid_rgba(w.document.get(new.id))[:3], BLUE)

    def test_without_project_default_bodies_are_program_grey(self):
        self.assertEqual(self.w.view.solid_rgba(self.a), SOLID_COLOR)


if __name__ == '__main__':
    unittest.main()


class ColorBatchTests(unittest.TestCase):
    """Duży szyk rysowany paczkami: kolor bryły i kolor domyślny także w paczkach."""
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_big_pattern_batches_keep_each_color(self):
        from dataclasses import replace
        from rccad.viewport import CadView
        view = CadView()
        self.addCleanup(view.deleteLater)
        source = Body('Walec', cq.Workplane('XY').circle(2.5).extrude(10).val()).prepared()
        bodies = [replace(source, id=f'copy-{i}', folder='szyk', shape=source.shape.translate(cq.Vector(i * 10, 0, 0)),
                          mesh=k.transformed_display_mesh(source.mesh, ('t', (i * 10, 0, 0))),
                          color=RED if i < 25 else None) for i in range(50)]
        view.set_models(bodies)
        colors = sorted(tuple(round(c, 3) for c in items[0].rccad_color[:3]) for items in [v[1:] for v in view._solid_batches.values()])
        self.assertEqual(colors, sorted([tuple(round(c, 3) for c in RED), tuple(round(c, 3) for c in SOLID_COLOR[:3])]))
        view.default_color = BLUE
        view.set_models(bodies)
        fills = {tuple(round(c, 3) for c in v[1].rccad_color[:3]) for v in view._solid_batches.values()}
        self.assertEqual(fills, {tuple(round(c, 3) for c in RED), tuple(round(c, 3) for c in BLUE)})
