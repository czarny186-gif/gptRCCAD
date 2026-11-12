"""Biblioteka obiektów i szkiców (zakładka Biblioteka)."""
import os
os.environ.setdefault('RCCAD_HISTORY_HOLD', '0')      # starsze testy: zmiany w historii przeliczane od razu (bez „Zatwierdź zmianę”)
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('RCCAD_WORKERS', '0')

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from rccad import kernel as k, library as lib
from rccad.document import Body


class LibraryFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'RCCAD_CONFIG_DIR': self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_folders_names_clipboard_and_storage_in_settings(self):
        home = lib.root('object')
        self.assertEqual(home, Path(self.tmp.name) / 'Biblioteka' / 'Obiekty')        # w folderze Ustawienia
        a = lib.new_folder(home)
        b = lib.new_folder(home)
        self.assertEqual([p.name for p in lib.entries('object', home)], ['Nowy folder', 'Nowy folder (2)'])
        a = lib.rename(a, 'Śruby/M8')                       # niedozwolone znaki zamienione
        self.assertEqual(a.name, 'Śruby_M8')
        body = Body('Wspornik', k.box(10, 5, 3)).prepared()
        saved = lib.save_bodies([body], a, 'Wspornik')
        self.assertEqual(saved.suffix, '.rccadx')
        again = lib.save_bodies([body], a, 'Wspornik')
        self.assertEqual(again.name, 'Wspornik (2).rccadx')
        loaded = lib.load_bodies('object', saved)
        self.assertEqual([x.name for x in loaded], ['Wspornik'])
        self.assertAlmostEqual(loaded[0].shape.Volume(), 150, 3)
        renamed = lib.rename(saved, 'Kątownik')
        self.assertEqual(renamed.name, 'Kątownik.rccadx')      # rozszerzenie zostaje
        moved = lib.paste([renamed], b, move=True)
        self.assertFalse(renamed.exists())
        self.assertTrue(moved[0].exists() and moved[0].parent == b)
        copied = lib.paste([b], home)                        # kopia folderu z zawartością
        self.assertTrue((copied[0] / 'Kątownik.rccadx').exists())
        with self.assertRaises(ValueError):
            lib.paste([b], b / '..' / b.name)                # folder do siebie samego
        lib.remove(copied[0])
        self.assertFalse(copied[0].exists())

    def test_import_and_export_keep_or_convert_format(self):
        home = lib.root('object')
        with tempfile.TemporaryDirectory() as outside:
            step = Path(outside) / 'Płyta.step'
            k.export_shapes([k.box(20, 20, 2)], step)
            junk = Path(outside) / 'notatki.txt'
            junk.write_text('x')
            made = lib.import_files('object', [step, junk], home)
            self.assertEqual([p.name for p in made], ['Płyta.step'])       # tylko formaty biblioteki
            out = Path(outside) / 'eksport'
            out.mkdir()
            self.assertEqual(lib.export_item('object', made[0], out).name, 'Płyta.step')        # bez zmiany formatu
            native = lib.save_bodies([Body('Kostka', k.box(5, 5, 5)).prepared()], home, 'Kostka')
            self.assertEqual(lib.export_item('object', native, out).name, 'Kostka.step')        # program -> STEP
            sketch = lib.save_bodies([Body('Okrąg', k.sketch('circle', 'XY', 6, 6), 'sketch', 'XY').prepared()], lib.root('sketch'), 'Okrąg')
            self.assertEqual(lib.export_item('sketch', sketch, out).name, 'Okrąg.dxf')         # szkic programu -> DXF
            self.assertEqual(lib.file_format(made[0]), 'STEP')
            loaded = lib.load_bodies('object', made[0])
            self.assertAlmostEqual(loaded[0].shape.Volume(), 800, 2)


class LibraryWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'RCCAD_CONFIG_DIR': self.tmp.name})
        self.env.start()
        from rccad.studio import StudioWindow
        self.w = StudioWindow()
        self.w.resize(1400, 850)
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.wait()
        for d in self.w.libraries.values():
            d.close()
        self.w.document._saved_revision = self.w.document._revision
        self.w.close()
        self.w.deleteLater()
        from PySide6.QtCore import QEvent
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.env.stop()
        self.tmp.cleanup()

    def wait(self):
        import time
        end = time.time() + 30
        while self.w.busy and time.time() < end:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()

    def test_tab_buttons_and_pick_place_flow(self):
        w = self.w
        self.assertIn('Biblioteka', w.tab_buttons)
        for key in ('libimport', 'libobj', 'libsketch'):
            self.assertIn(key, w.tools)
        box = Body('Wspornik', k.box(10, 10, 10)).prepared()
        w.document.commit([box])
        w.refresh()
        w.tools['libobj'].click()
        d = w.libraries['object']
        self.assertTrue(d.isVisible())
        d.add_folder()
        self.app.processEvents()
        folder = lib.entries('object', d.home)[0]
        d.enter(folder)
        self.assertTrue(d.back_btn.isEnabled() and d.home_btn.isEnabled())
        d.take_from_workspace()
        self.assertFalse(d.isVisible())                         # okno chowa się na czas wskazywania
        w.context_menu(5, 5)                                     # prawy przycisk anuluje
        self.assertTrue(d.isVisible())
        self.assertIsNone(w._lib_action)
        d.take_from_workspace()
        with patch.object(w, 'pick_object', return_value=box.id):
            w.view_hover(5, 5)
            self.assertEqual(w._obj_hover, box.id)                  # podświetlenie przed kliknięciem
            w.view_clicked(5, 5, False, False)
        self.assertTrue(d.isVisible())
        self.assertEqual(w._obj_hover, '')
        files = [p for p in lib.entries('object', folder) if p.is_file()]
        self.assertEqual([p.name for p in files], ['Wspornik.rccadx'])
        self.assertEqual([Path(i.data(Qt.UserRole)) for i in d.view.selectedItems()], files)
        d.place_selected()
        self.wait()
        self.assertFalse(d.isVisible())
        with patch.object(w, '_library_target', return_value=(np.array([100.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 'Siatka')):
            w.view_hover(5, 5)
            self.assertTrue(w.view.preview_items)                  # element idzie za kursorem
            self.assertEqual(w.view.snap_marker[1], 'Siatka')      # znacznik miejsca na siatce
            w.view_clicked(5, 5, False, False)
        self.wait()
        self.assertTrue(d.isVisible())
        self.assertEqual(len(w.document.bodies), 2)
        placed = w.document.bodies[-1]
        bb = placed.shape.BoundingBox()
        self.assertAlmostEqual(bb.zmin, 0, 4)                    # stoi spodem na wskazanym miejscu
        self.assertAlmostEqual((bb.xmin + bb.xmax) / 2, 100, 4)
        self.assertNotEqual(placed.id, box.id)
        d.go_home()
        self.assertFalse(d.back_btn.isEnabled())

    def test_several_bodies_or_a_group_save_as_one_entry_and_insert_separately(self):
        w = self.w
        a = Body('Noga', k.box(4, 4, 20), folder='Stolik').prepared()
        b = Body('Blat', k.transform(k.box(30, 20, 2), (0, 0, 20)), folder='Stolik').prepared()
        c = Body('Kostka', k.transform(k.box(5, 5, 5), (60, 0, 0))).prepared()
        w.document.commit([a, b, c])
        w.refresh()
        w.tools['libobj'].click()
        d = w.libraries['object']
        d.take_from_workspace()
        self.assertTrue(w.lib_panel.isVisible())
        w.objects_folder_select([a.id, b.id])                    # cała grupa z listy Obiekty
        self.assertEqual(w._lib_action['ids'], [a.id, b.id])
        with patch.object(w, 'pick_object', return_value=c.id):
            w.view_clicked(5, 5, True, False)                   # Shift + klik - kolejna
        self.assertEqual(w._lib_action['ids'], [a.id, b.id, c.id])
        w.objects_select(c.id, Qt.NoModifier)                    # ponownie - odchodzi
        self.assertEqual(w._lib_action['ids'], [a.id, b.id])
        w.lib_save.click()
        self.assertIsNone(w._lib_action)
        self.assertFalse(w.lib_panel.isVisible())
        self.assertTrue(d.isVisible())
        files = [p for p in lib.entries('object', d.folder) if p.is_file()]
        self.assertEqual([p.name for p in files], ['Stolik.rccadx'])
        self.assertEqual(len(lib.load_bodies('object', files[0])), 2)           # jeden plik, dwie osobne bryły
        d.view.clearSelection()
        for i in range(d.view.count()):
            if Path(d.view.item(i).data(Qt.UserRole)) == files[0]:
                d.view.item(i).setSelected(True)
        d.place_selected()
        self.wait()
        with patch.object(w, '_library_target', return_value=(np.array([100.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), 'Siatka')):
            w.view_clicked(5, 5, False, False)
        self.wait()
        placed = w.document.bodies[3:]
        self.assertEqual(len(placed), 2)                         # wstawione jako dwie niepołączone bryły
        self.assertEqual({p.name for p in placed}, {'Noga', 'Blat'})
        self.assertEqual(len({p.folder for p in placed}), 1)
        self.assertAlmostEqual(sum(p.shape.Volume() for p in placed), 4 * 4 * 20 + 30 * 20 * 2, 3)
        # zaznaczone przed „Wstaw z pola roboczego” - od razu wybrane
        w.selected = [a.id, c.id]
        d.take_from_workspace()
        self.assertEqual(w._lib_action['ids'], [a.id, c.id])
        w.library_cancel()

    def test_sketch_library_and_clipboard_in_window(self):
        w = self.w
        sk = Body('Okrąg', k.sketch('circle', 'XY', 8, 8), 'sketch', 'XY').prepared()
        solid = Body('Kostka', k.box(5, 5, 5)).prepared()
        w.document.commit([sk, solid])
        w.refresh()
        d = w.open_library('sketch')
        d.take_from_workspace()
        with patch.object(w, 'pick_object', return_value=solid.id):
            w.view_hover(5, 5)
            self.assertEqual(w._obj_hover, '')                     # bryła nie podświetla się w bibliotece szkiców
            w.view_clicked(5, 5, False, False)                     # bryła nie jest szkicem - czeka dalej
        self.assertIsNotNone(w._lib_action)
        with patch.object(w, 'pick_object', return_value=sk.id):
            w.view_clicked(5, 5, False, False)
        saved = [p for p in lib.entries('sketch', d.home) if p.is_file()]
        self.assertEqual(len(saved), 1)
        d.add_folder()
        self.app.processEvents()
        target = next(p for p in lib.entries('sketch', d.home) if p.is_dir())
        d.view.clearSelection()
        for i in range(d.view.count()):
            item = d.view.item(i)
            item.setSelected(Path(item.data(Qt.UserRole)) == saved[0])
        d.copy(True)                                               # wytnij
        d.enter(target)
        d.paste_here()
        self.assertEqual([p.name for p in lib.entries('sketch', target)], ['Okrąg.rccadx'])
        self.assertFalse(saved[0].exists())
        d.place_selected()
        self.wait()
        with patch.object(w, '_library_target', return_value=(np.array([30.0, 0.0, 20.0]), np.array([1.0, 0.0, 0.0]), 'Ściana')):
            w.view_clicked(5, 5, False, False)
        self.wait()
        new = w.document.bodies[-1]
        self.assertEqual(new.kind, 'sketch')
        frame = k.frame_of(new.plane)
        self.assertTrue(np.allclose(frame.normal, [1, 0, 0], atol=1e-9))         # szkic położony na ścianie bocznej
        bb = new.shape.BoundingBox()
        self.assertAlmostEqual(bb.xmin, 30, 4); self.assertAlmostEqual(bb.xmax, 30, 4)
        self.assertAlmostEqual((bb.zmin + bb.zmax) / 2, 20, 4)
        with patch.object(lib.QMessageBox, 'question', return_value=lib.QMessageBox.Yes):
            d.go_home()
            for i in range(d.view.count()):
                d.view.item(i).setSelected(True)
            d.delete_selected()
        self.assertEqual(lib.entries('sketch', d.home), [])


if __name__ == '__main__':
    unittest.main()
