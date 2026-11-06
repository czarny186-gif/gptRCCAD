"""Plik projektu wersji 3: geometria w jednej paczce, opis kroków bez powtórzeń, zapis kompaktowy i zgodność ze starszymi plikami."""
import json, os, tempfile, unittest, zipfile
import cadquery as cq
from rccad import kernel as k, history as hist, sheetedit as she, sheetmetal as shm
from rccad.document import Body, Document


def same(test, a, b):
    test.assertEqual(len(a.states()), len(b.states()))
    for (ba, ia), (bb, ib) in zip(a.states(), b.states()):
        test.assertEqual([x.id for x in ba], [y.id for y in bb])
        test.assertEqual((ia.get('label'), ia.get('op')), (ib.get('label'), ib.get('op')))
        test.assertFalse(ib.get('stale'))
        for x, y in zip(ba, bb):
            test.assertEqual((x.name, x.kind, x.visible, x.meta), (y.name, y.kind, y.visible, y.meta))
            test.assertAlmostEqual(x.shape.Volume(), y.shape.Volume(), 5)


class ProjectFileTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def sheet_document(self):
        """Blacha: konwersja, cztery kołnierze, rozłożenie, zgięcie i przesunięcie - kroki z przepisami."""
        d = Document()
        t = 1.0
        base = dict(o=[0, 0, 0], x=[1, 0, 0], y=[0, 1, 0], z=[0, 0, 1], lx=60, ly=40, lz=t)
        rules = dict(gap=.1, relief='none', relief_size=3, joint='sheet', miter=True, auto_corners=True, kfactor=.44)
        plate = Body('Blacha', shm.build_sheet(dict(base=base, t=t, flanges=[], rules=rules)), meta={'sheet': she.state(dict(base=base, t=t, flanges=[], rules=rules))}).prepared()
        d.commit([plate], label='Konwersja na blachę')
        edges = [([60, 0, t], [60, 40, t], [1, 0, 0]), ([60, 40, t], [0, 40, t], [0, 1, 0]), ([0, 40, t], [0, 0, t], [-1, 0, 0]), ([0, 0, t], [60, 0, t], [0, -1, 0])]
        flanges = []
        for a, b, m in edges:
            flanges.append(dict(kind='base', p0=a, p1=b, n=[0, 0, 1], m=m, r=.5, angle=90, length=5, measure='outer'))
            recipe = dict(type='sheetbuild', id=plate.id, base=base, t=t, flanges=list(flanges), rules=rules)
            d.commit(hist.run_recipe(d.bodies, recipe), label='Kołnierz', op=recipe)
        for flat, label in ((True, 'Rozłóż blachę'), (False, 'Zegnij blachę')):
            body = d.get(plate.id)
            recipe = dict(type='sheetmode', id=plate.id, state=body.meta['sheet'], flat=flat, sync=False)
            d.commit(hist.run_recipe(d.bodies, recipe), label=label, op=recipe)
        recipe = dict(type='transform', id=plate.id, mode='move', v=[15.0, 0.0, 0.0])
        d.commit(hist.run_recipe(d.bodies, recipe), label='Przekształcenie', op=recipe)
        return d

    def test_pack_and_tables_roundtrip(self):
        d = self.sheet_document()
        path = os.path.join(self.dir, 'p.rccadx')
        d.save(path)
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            manifest = json.loads(z.read('manifest.json'))
        self.assertEqual(sorted(names), ['manifest.json', 'shapes.pack'])          # cała geometria w jednej paczce
        self.assertEqual(manifest['version'], 3)
        self.assertTrue(all(isinstance(ref, int) for st in manifest['states'] for ref in st['bodies']))
        self.assertLess(len(manifest['metas']), sum(len(st['bodies']) for st in manifest['states']) + 1)
        same(self, d, Document.load(path))

    def test_compact_save_replays_steps_on_open(self):
        d = self.sheet_document()
        full, small = os.path.join(self.dir, 'full.rccadx'), os.path.join(self.dir, 'small.rccadx')
        d.save(full)
        d.save(small, compact=True)
        with zipfile.ZipFile(small) as z:
            manifest = json.loads(z.read('manifest.json'))
        self.assertGreater(manifest['virtual'], 0)
        self.assertLess(os.path.getsize(small), os.path.getsize(full))
        loaded = Document.load(small)
        same(self, d, loaded)
        self.assertEqual(len(loaded._undo), len(d._undo))

    def test_long_history_with_many_changed_bodies_reopens(self):
        d = Document()
        bodies = [Body(f'B{i}', k.box(1, 1, 1).translate((i * 2, 0, 0))).prepared() for i in range(4)]
        d.commit(bodies)
        for step in range(820):           # dawny format: ponad 3000 plików geometrii -> „Projekt jest zbyt duży”
            bodies = [Body(b.name, k.box(1 + step * 1e-4 + j * 1e-3, 1, 1).translate((j * 2, 0, 0)), id=b.id) for j, b in enumerate(bodies)]
            d.commit(bodies, label=f'krok {step}')
        path = os.path.join(self.dir, 'long.rccadx')
        d.save(path)
        loaded = Document.load(path)
        self.assertEqual(len(loaded.states()), len(d.states()))
        self.assertAlmostEqual(loaded.bodies[3].shape.Volume(), d.bodies[3].shape.Volume(), 9)

    def test_version_two_projects_still_open(self):
        shape = k.box(10, 20, 30)
        brep = os.path.join(self.dir, 's.brep')
        cq.exporters.export(shape, brep, exportType='BREP')
        body = dict(id='a' * 32, name='Kostka', kind='solid', plane='XY', visible=True, shape=0, meta={'note': 'x'})
        manifest = dict(app='RCCAD_DESKTOP', version=2, units='mm', shapes=['shapes/0.brep'], current=1, constraints=[], variables={},
                        states=[dict(label='Początek', icon='start', bodies=[]), dict(label='Kostka', icon='file', bodies=[body])])
        path = os.path.join(self.dir, 'v2.rccadx')
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('manifest.json', json.dumps(manifest))
            z.write(brep, 'shapes/0.brep')
        loaded = Document.load(path)
        self.assertEqual(loaded.bodies[0].name, 'Kostka')
        self.assertEqual(loaded.bodies[0].meta, {'note': 'x'})
        self.assertAlmostEqual(loaded.bodies[0].shape.Volume(), 6000, 6)

    def test_history_limit_counts_dropped_steps(self):
        d = Document()
        body = Body('A', k.box(1, 1, 1)).prepared()
        for i in range(d.MAX_UNDO + 5):
            d.commit([body], label=str(i))
        self.assertEqual(d.history_length, d.MAX_UNDO)
        self.assertEqual(d.dropped, 5)

    def test_step_labels_show_values(self):
        self.assertEqual(hist.step_label(dict(label='Kołnierz', op=dict(type='sheetbuild', flanges=[dict(length=20, angle=90)]))), 'Kołnierz 20 mm, 90°')
        self.assertEqual(hist.step_label(dict(label='Przekształcenie', op=dict(type='transform', mode='move', v=[15, 0, -2.5]))), 'Przesunięcie X +15 mm, Z -2,5 mm')
        self.assertEqual(hist.step_label(dict(label='Wyciągnięcie', op=dict(type='extrude', d1=10, dir='one'))), 'Wyciągnięcie 10 mm')
        self.assertEqual(hist.step_label(dict(label='Tworzenie szkicu')), 'Tworzenie szkicu')
        d = self.sheet_document()
        labels, _ = d.timeline()
        self.assertIn('Kołnierz 5 mm, 90°', labels)
        self.assertIn('Przesunięcie X +15 mm', labels)


if __name__ == '__main__':
    unittest.main()
