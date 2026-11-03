"""Rysunek techniczny: rzuty HLR, wymiary, układ arkusza oraz eksport do PDF / DXF / SVG / JPG."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen' if not os.environ.get('DISPLAY') and os.name != 'nt' else '')
import tempfile
import unittest
from pathlib import Path
import cadquery as cq
from PySide6.QtWidgets import QApplication
from rccad import drawing as D


def plate():
    return cq.Workplane('XY').box(60, 40, 20).faces('>Z').workplane().hole(10).val()


class DrawingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.source = D.DrawingSource(plate(), 'Płytka')

    def test_projection_sizes(self):
        front, top, right = (self.source.view(n).bbox for n in ('front', 'top', 'right'))
        self.assertAlmostEqual(front[2] - front[0], 60, 1); self.assertAlmostEqual(front[3] - front[1], 20, 1)
        self.assertAlmostEqual(top[2] - top[0], 60, 1); self.assertAlmostEqual(top[3] - top[1], 40, 1)
        self.assertAlmostEqual(right[2] - right[0], 40, 1); self.assertAlmostEqual(right[3] - right[1], 20, 1)

    def test_hole_found_only_in_top_view(self):
        self.assertTrue(any(abs(c['r'] - 5) < 1e-3 and c['full'] for c in self.source.view('top').circles))
        self.assertFalse(self.source.view('front').circles)

    def test_drawing_contents_and_scale(self):
        d = D.build_drawing(self.source, ('front', 'top', 'right', 'iso'))
        texts = [p.text for p in d.prims if isinstance(p, D.Label)]
        for expected in ('60', '40', '20', 'Ø10'):
            self.assertIn(expected, texts)
        self.assertIn('Płytka', texts)
        self.assertGreaterEqual(d.scale, 1)
        for p in d.prims:
            if isinstance(p, D.Poly):
                for x, y in p.pts:
                    self.assertTrue(0 <= x <= d.width and 0 <= y <= d.height)
        self.assertEqual(set(d.views), {'front', 'top', 'right', 'iso'})

    def test_hidden_lines_and_auto(self):
        a = D.build_drawing(self.source, ('front',), hidden=False)
        b = D.build_drawing(self.source, ('front',), hidden=True)
        self.assertGreater(len([p for p in b.prims if getattr(p, 'style', '') == 'hidden']), 0)
        self.assertEqual(len([p for p in a.prims if getattr(p, 'style', '') == 'hidden']), 0)
        auto = D.auto_settings(self.source)
        self.assertEqual(auto['views'], ('front', 'top', 'right', 'iso'))
        self.assertTrue(D.build_drawing(self.source, **auto).prims)

    def test_big_part_gets_smaller_scale(self):
        big = D.DrawingSource(cq.Workplane('XY').box(900, 600, 300).val(), 'Duża')
        d = D.build_drawing(big, ('front', 'top', 'right'))
        self.assertLess(d.scale, 1)

    def test_exports(self):
        from rccad.drawing_window import export_drawing
        d = D.build_drawing(self.source, ('front', 'top', 'right'), version='test')
        with tempfile.TemporaryDirectory() as tmp:
            for ext in ('pdf', 'dxf', 'svg', 'jpg'):
                path = Path(tmp) / f'r.{ext}'
                export_drawing(d, path)
                self.assertGreater(path.stat().st_size, 500, ext)
            self.assertTrue((Path(tmp) / 'r.pdf').read_bytes().startswith(b'%PDF'))
            self.assertIn(b'<svg', (Path(tmp) / 'r.svg').read_bytes()[:600] + (Path(tmp) / 'r.svg').read_bytes()[600:2000])
            self.assertEqual((Path(tmp) / 'r.jpg').read_bytes()[:2], b'\xff\xd8')
            text = (Path(tmp) / 'r.dxf').read_text(encoding='cp1250')
            self.assertIn('ENTITIES', text); self.assertIn('LINE', text); self.assertIn('%%c10', text)

    def test_window_measure_and_rebuild(self):
        from rccad.drawing_window import DrawingWindow
        win = DrawingWindow(plate(), 'Płytka'); win.show()
        for _ in range(300):
            self.app.processEvents()
            if win.drawing is not None:
                break
            import time; time.sleep(0.05)
        self.assertIsNotNone(win.drawing)
        view_w = win.side_scroll.viewport().width()          # panel boczny nie może być ucięty z prawej strony
        for key, tile in win.view_boxes.items():
            right = tile.mapTo(win.side_scroll.viewport(), tile.rect().bottomRight()).x()
            self.assertTrue(tile.isVisibleTo(win) and 0 <= right <= view_w, (key, right, view_w))
        for box in list(win.opt.values()):
            self.assertLessEqual(box.mapTo(win.side_scroll.viewport(), box.rect().bottomRight()).x(), view_w, box.text())
        d = win.drawing; c = win.canvas
        hole = [f for f in d.features if f['kind'] == 'circle' and f['view'] == 'top'][0]
        r1 = c.ref_at(hole['c']); self.assertEqual(r1['kind'], 'center')
        self.assertIsNone(c.ref_at((1.0, 1.0)))           # puste miejsce arkusza - brak punktu do pomiaru
        edge = [f for f in d.features if f['kind'] == 'line' and f['view'] == 'top' and abs(f['a'][0] - f['b'][0]) < 1e-6][0]
        r2 = c.ref_at((edge['a'][0] + 0.2, edge['a'][1] + 0.3 * (edge['b'][1] - edge['a'][1])))
        self.assertEqual(r2['kind'], 'edge')
        text = c.describe((r1, r2))
        self.assertIn('mm', text)
        m = c._make_dist(r1, r2)                           # od środka otworu do krawędzi: odległość prostopadła
        self.assertIsNotNone(m)
        P, Q = m['mdl']
        self.assertAlmostEqual(abs(Q[0] - P[0]), 30.0, 1)     # otwór w środku płytki 60 mm
        c.pairs.append((r1, r2)); c._pair_to_dim(0)
        self.assertIsNotNone(c.placing); self.assertEqual(c.pairs, [])
        c.place_at((hole['c'][0] + 5, hole['c'][1] - 20)); self.assertEqual(len(c.manual), 1)
        self.assertIn('30', [p.text for p in c.composed().prims if isinstance(p, D.Label)])
        c.clear_dims()
        win.view_boxes['iso'].setChecked(True); win._timer.stop(); win._start()
        for _ in range(300):
            self.app.processEvents()
            if win.drawing is not d:
                break
            import time; time.sleep(0.05)
        self.assertIn('iso', win.drawing.views)
        win.close()

    def test_manual_dimensions(self):
        from rccad.drawing_window import DrawingWindow, export_drawing
        import time
        win = DrawingWindow(plate(), 'Płytka'); win.show()
        for _ in range(300):
            self.app.processEvents()
            if win.drawing is not None:
                break
            time.sleep(0.05)
        c = win.canvas; d = win.drawing
        self.assertFalse([p for p in d.prims if isinstance(p, D.Label) and p.text == 'Ø10'])      # domyślnie bez wymiarów automatycznych
        hole = [f for f in d.features if f['kind'] == 'circle' and f['view'] == 'top' and abs(f['mdl'][1] - 5) < 1e-3][0]
        found = c.feature_at(hole['c'])
        self.assertIsNotNone(found); self.assertEqual(found['kind'], 'circle')
        c.start_placing(found)
        c.place_at((hole['c'][0] + 20, hole['c'][1] + 15))
        edge = [f for f in d.features if f['kind'] == 'line' and f['view'] == 'front'][0]
        mid = ((edge['a'][0] + edge['b'][0]) / 2, (edge['a'][1] + edge['b'][1]) / 2)
        c.start_placing(c.feature_at(mid)); c.place_at((mid[0] + 8, mid[1] + 8))
        self.assertEqual(len(c.manual), 2)
        texts = [p.text for p in c.composed().prims if isinstance(p, D.Label)]
        self.assertIn('Ø10', texts)
        self.assertTrue({'60', '20'} & set(texts))
        # wymiar przeżywa zmianę skali / układu
        win.scale.setCurrentIndex(win.scale.findData(2)); win._timer.stop(); win._start()
        for _ in range(300):
            self.app.processEvents()
            if win.drawing is not d:
                break
            time.sleep(0.05)
        self.assertEqual(len(c.manual), 2); self.assertIn('Ø10', [p.text for p in c.composed().prims if isinstance(p, D.Label)])
        with tempfile.TemporaryDirectory() as tmp:
            export_drawing(c.composed(), Path(tmp) / 'm.dxf')
            self.assertIn('%%c10', (Path(tmp) / 'm.dxf').read_text(encoding='cp1250'))
        c.undo_dim(); self.assertEqual(len(c.manual), 1)
        win.close()

    def test_contour_dims_for_slot_and_polygon(self):
        slot = cq.Workplane('XY').box(80, 50, 10).faces('>Z').workplane().slot2D(30, 10).cutThruAll()
        hexa = cq.Workplane('XY').polygon(6, 40).extrude(15)
        for name, w in (('Fasolka', slot), ('Sześciokąt', hexa)):
            src = D.DrawingSource(w.val(), name)
            plain = D.build_drawing(src, ('top',), details=False, overall=False, circles=False)
            full = D.build_drawing(src, ('top',), details=True, overall=False, circles=False)
            count = lambda d: len([p for p in d.prims if isinstance(p, D.Label)])
            self.assertGreaterEqual(count(full), count(plain) + 2, name)
        texts = [p.text for p in D.build_drawing(D.DrawingSource(slot.val(), 'F'), ('top',), details=True).prims if isinstance(p, D.Label)]
        self.assertIn('20', texts)          # prosta część fasolki (30 mm razem z końcami)
        self.assertIn('R5', texts)
        self.assertIn('30', texts)          # cała długość fasolki, od końca do końca łuków
        arcs = [c for c in D.DrawingSource(slot.val(), 'F').view('top').circles if not c['full']]
        self.assertEqual(sorted(round(c['r'], 2) for c in arcs), [5.0, 5.0])


    def test_figure_centers_radius_and_text(self):
        from rccad.drawing_window import DrawingWindow, export_drawing
        import time
        hexa = cq.Workplane('XY').polygon(6, 40).extrude(15).val()
        win = DrawingWindow(hexa, 'Sześciokąt'); win.show()
        for _ in range(300):
            self.app.processEvents()
            if win.drawing is not None:
                break
            time.sleep(0.05)
        c = win.canvas; d = win.drawing
        centers = [f for f in d.features if f['kind'] == 'fcenter' and f['view'] == 'top']
        self.assertEqual(len(centers), 1)
        ref = c.ref_at(centers[0]['c']); self.assertEqual(ref['kind'], 'fcenter')
        vert = c.ref_at([f for f in d.features if f['kind'] == 'line' and f['view'] == 'top'][0]['a'])
        self.assertEqual(vert['kind'], 'end')
        m = c._make_dist(ref, vert)
        self.assertTrue(m['radial'] and m['aligned'])
        c.placing = m; c.place_at((centers[0]['c'][0] + 15, centers[0]['c'][1] + 30))
        texts = [p.text for p in c.composed().prims if isinstance(p, D.Label)]
        self.assertIn('R20', texts)                        # promień okręgu opisanego na sześciokącie 40 mm
        # tekst wielowierszowy w wybranym miejscu, ze strzałką do elementu
        c.set_tool('text')
        item = c.add_text((100.0, 100.0), dict(text='Materiał: stal\nDruga linia', font='Arial', h=3.5, bold=True, italic=False))
        composed = c.composed()
        labels = [p for p in composed.prims if isinstance(p, D.Label)]
        self.assertIn('Materiał: stal\nDruga linia', [p.text for p in labels])
        before = len(composed.prims)
        target = c.ref_at(centers[0]['c'])
        item['leader'] = dict(view=target['view'], mdl=tuple(target['pt']))
        self.assertGreater(len(c.composed().prims), before + 1)        # linia odniesienia i grot
        box = D.text_box(c.drawing, item)
        self.assertGreater(box[3] - box[1], 7.0)                       # dwie linie
        item['mdl'] = (item['mdl'][0] + 5.0, item['mdl'][1] + 5.0) if item['view'] else (item['mdl'][0] + 5.0, item['mdl'][1] + 5.0)
        with tempfile.TemporaryDirectory() as tmp:
            for ext in ('pdf', 'svg', 'dxf', 'jpg'):
                export_drawing(c.composed(), Path(tmp) / f't.{ext}')
            dxf = (Path(tmp) / 't.dxf').read_text(encoding='cp1250')
            self.assertIn('Materia', dxf); self.assertIn('Druga linia', dxf)
        c.undo_dim(); self.assertEqual(len([m for m in c.manual if m['kind'] == 'text']), 0)
        win.close()

    def test_slot_center_found(self):
        slot = cq.Workplane('XY').box(80, 50, 10).faces('>Z').workplane().slot2D(30, 10).cutThruAll().val()
        g = D.DrawingSource(slot, 'F').view('top')
        self.assertTrue(any(abs(c[0]) < 0.1 and abs(c[1]) < 0.1 for c in g.centers))


    def test_blind_holes_and_pockets_are_drawn(self):
        """Otwory i kieszenie nie na wylot też widać na rzucie od strony wycięcia (i jako linie niewidoczne z boku)."""
        base = lambda: cq.Workplane('XY').box(60, 40, 20).faces('>Z').workplane()
        cases = {
            'otwór': base().hole(10, 8).val(),
            'prostokąt': base().rect(20, 10).cutBlind(-6).val(),
            'sześciokąt': base().polygon(6, 14).cutBlind(-6).val(),
            'fasolka': base().slot2D(30, 10).cutBlind(-6).val(),
            'okrąg': base().circle(6).cutBlind(-6).val(),
        }
        report = {}
        for name, shape in cases.items():
            src = D.DrawingSource(shape, name)
            top = src.view('top')
            near = lambda q: min((D._near_segments(__import__('numpy').array(p[:-1]), __import__('numpy').array(p[1:]), q) for p in top.visible if len(p) > 1), default=99)
            d = D.build_drawing(src, ('top',), details=True)
            hid = D.build_drawing(src, ('front',), hidden=True)
            labels = [p.text for p in d.prims if isinstance(p, D.Label)]
            report[name] = dict(circles=[(round(c['r'], 2), c['full']) for c in top.circles], centers=len(top.centers),
                                features=len([f for f in d.features if f['view'] == 'top']), labels=labels,
                                hidden=len([p for p in hid.prims if getattr(p, 'style', '') == 'hidden']), visible=len(top.visible))
        problems = []
        if (5.0, True) not in report['otwór']['circles']: problems.append('otwór: brak okręgu')
        if (6.0, True) not in report['okrąg']['circles']: problems.append('okrąg: brak okręgu')
        for name in ('prostokąt', 'sześciokąt', 'fasolka'):
            if report[name]['centers'] < 1: problems.append(name + ': brak środka figury')
        if not any(c[0] == 5.0 and not c[1] for c in report['fasolka']['circles']): problems.append('fasolka: brak łuków')
        for name, r in report.items():
            if r['hidden'] < 1: problems.append(name + ': brak linii niewidocznych w rzucie z przodu')
            if 'Ø10' not in r['labels'] and name == 'otwór': problems.append('otwór: brak wymiaru Ø10')
        self.assertFalse(problems, str(problems) + ' ' + str(report))


    def test_hidden_edges_can_be_picked_to_measure_pocket_depth(self):
        shape = cq.Workplane('XY').box(60, 40, 20).faces('>Z').workplane().rect(20, 10).cutBlind(-6).val()
        src = D.DrawingSource(shape, 'Kieszeń')
        off = D.build_drawing(src, ('front',), hidden=False)
        on = D.build_drawing(src, ('front',), hidden=True)
        self.assertFalse([f for f in off.features if f.get('hidden')])
        hid = [f for f in on.features if f.get('hidden')]
        self.assertTrue(hid, 'brak niewidocznych krawędzi do wskazania')
        depths = {round(abs(f['mdl'][0][1] - 10.0), 1) for f in hid if abs(f['mdl'][0][1] - f['mdl'][1][1]) < 1e-6}
        self.assertIn(6.0, depths)

    def test_cube_has_all_six_views_inside_the_sheet(self):
        cube = D.DrawingSource(cq.Workplane('XY').box(40, 40, 40).val(), 'Sześcian')
        for projection in ('eu', 'us'):
            d = D.build_drawing(cube, ('front', 'back', 'left', 'right', 'top', 'bottom', 'iso'), projection=projection)
            self.assertEqual(set(d.views), {'front', 'back', 'left', 'right', 'top', 'bottom', 'iso'})
            boxes = []
            for name, v in d.views.items():
                x0, y0, x1, y1 = v['bbox']
                self.assertGreater(x1 - x0, 1.0, name); self.assertGreater(y1 - y0, 1.0, name)
                self.assertTrue(20 <= x0 and x1 <= d.width - 10 and 10 <= y0 and y1 <= d.height - 10, (projection, name, v['bbox']))
                boxes.append((name, v['bbox']))
            for i, (n1, a) in enumerate(boxes):
                for n2, b in boxes[i + 1:]:
                    self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3], (n1, n2))


if __name__ == '__main__':
    unittest.main()
