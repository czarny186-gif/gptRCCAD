"""Zakładka Sklejka: płyty, ścianki, półki, rozpoznawanie styków, połączenia zależne od metody produkcji, pliki do cięcia."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen' if not os.environ.get('DISPLAY') and os.name != 'nt' else '')
os.environ['RCCAD_CONFIG_DIR'] = tempfile.mkdtemp(prefix='rccad-cfg-')
os.environ.setdefault('RCCAD_WORKERS', '0')

import cadquery as cq
import numpy as np

from rccad import history as hist
from rccad import kernel as k
from rccad import plywood as pw
from rccad.document import Body


def _panel(pid, shape, t):
    return dict(id=pid, shape=shape, **pw.panel_info(shape, t))


def _box(t=6.0):
    """Podstawa 200 × 150 z czterema ściankami 80 mm (dłuższe przez całą długość) i półką między dłuższymi."""
    base = cq.Solid.makeBox(200, 150, t)
    edges = sorted([e for e in base.Edges() if abs(e.Center().z - t) < 1e-6], key=lambda e: -e.Length())
    walls = []
    for e in edges:
        w, _ = pw.edge_wall(base, e, t, 80, 'on')
        for o in walls:
            if w.intersect(o).Volume() > 1e-6:
                w = w.cut(o)
        walls.append(k.valid(w.clean()))
    return base, walls


def _overlaps(shapes):
    bad = 0
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            if shapes[i].intersect(shapes[j]).Volume() > 1e-3:
                bad += 1
    return bad


class PlywoodGeometryTests(unittest.TestCase):
    def test_methods_allow_only_possible_joints(self):
        self.assertFalse(pw.allowed('laser', 'blind'))
        self.assertFalse(pw.allowed('laser', 'groove'))
        self.assertTrue(pw.allowed('cnc', 'blind') and pw.allowed('print', 'groove'))
        self.assertEqual(pw.joint_for('laser', 'T', 'groove'), 'tab')          # rowek przy laserze -> czopy przelotowe
        self.assertEqual(pw.joint_for('cnc', 'T', 'groove'), 'groove')
        self.assertEqual(pw.joint_for('laser', 'X'), 'halving')
        self.assertEqual(pw.joint_for('cnc', 'L'), 'finger')
        for n in (3, 5, 7, 9):
            self.assertEqual(pw.finger_count(n * 10, 10), n)
        self.assertEqual(pw.finger_count(100, 10) % 2, 1)                       # zawsze nieparzysta

    def test_panel_info_and_edge_wall_modes(self):
        base = cq.Solid.makeBox(100, 50, 6)
        info = pw.panel_info(base)
        self.assertTrue(np.allclose(np.abs(info['n']), [0, 0, 1]))
        self.assertAlmostEqual(info['t'], 6)
        e = next(x for x in base.Edges() if abs(x.Center().z - 6) < 1e-6 and abs(x.Center().y) < 1e-6)
        for side, flip, box in (('on', False, (0, 6, 6, 46)), ('side', False, (-6, 0, 0, 46)), ('on', True, (0, 6, -40, 0)), ('side', True, (-6, 0, -40, 6))):
            w, _ = pw.edge_wall(base, e, 6, 40, side, flip)
            bb = w.BoundingBox()
            self.assertTrue(np.allclose((bb.ymin, bb.ymax, bb.zmin, bb.zmax), box, atol=1e-6), (side, flip))
            self.assertLess(w.intersect(base).Volume(), 1e-6)                   # stoi przy podstawie, nie w niej
        thick = next(x for x in base.Edges() if abs(x.Center().z - 3) < 1e-6)
        with self.assertRaises(k.CadError):
            pw.edge_wall(base, thick, 6, 40)

    def test_contacts_corner_tee_and_cross(self):
        base, walls = _box()
        panels = [_panel('base', base, 6)] + [_panel(f'w{i}', w, 6) for i, w in enumerate(walls)]
        contacts, skipped = pw.find_contacts(panels)
        kinds = sorted(c['kind'] for c in contacts)
        self.assertEqual(kinds, ['L'] * 8)                                      # 4 ścianki z podstawą, 4 narożniki
        self.assertFalse(skipped)
        a = cq.Solid.makeBox(400, 18, 200).translate(cq.Vector(0, 100, 0))
        b = cq.Solid.makeBox(18, 300, 200).translate(cq.Vector(150, 0, 0))
        found, _ = pw.find_contacts([_panel('a', a, 18), _panel('b', b, 18)])
        self.assertEqual([c['kind'] for c in found], ['X'])
        side = cq.Solid.makeBox(18, 300, 400)
        shelf = cq.Solid.makeBox(282, 280, 18).translate(cq.Vector(18, 0, 200))
        found, _ = pw.find_contacts([_panel('s', side, 18), _panel('p', shelf, 18)])
        self.assertEqual([(c['a'], c['b'], c['kind']) for c in found], [('p', 's', 'T')])   # półka w środku boku
        found, _ = pw.find_contacts([dict(_panel('s', side, 18), joined={'p'}), _panel('p', shelf, 18)])
        self.assertEqual(found, [])                                             # już połączone - pomijane

    def test_joints_for_each_method_fit_without_overlap(self):
        base, walls = _box()
        panels = [_panel('base', base, 6)] + [_panel(f'w{i}', w, 6) for i, w in enumerate(walls)]
        contacts, _ = pw.find_contacts(panels)
        for meth in ('laser', 'cnc', 'print'):
            for c in contacts:
                c['joint'] = pw.joint_for(meth, c['kind'])
            m = pw.METHODS[meth]
            out = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method=meth, fit=m['fit'], tool=m['tool']))
            self.assertEqual(set(out), {p['id'] for p in panels})
            shapes = [out[p['id']] for p in panels]
            self.assertTrue(all(s.isValid() for s in shapes))
            self.assertEqual(_overlaps(shapes), 0, meth)                        # płyty po połączeniu nie nachodzą na siebie
            self.assertNotAlmostEqual(out['w0'].Volume(), walls[0].Volume(), 0)    # wczepy zmieniły płyty
        with self.assertRaises(k.CadError):                                      # gniazdo nieprzelotowe laserem - nie
            contacts[0]['joint'] = 'blind'
            pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts[:1], dict(method='laser'))

    def test_cnc_dogbones_and_blind_pocket_layers(self):
        side = cq.Solid.makeBox(18, 300, 400)
        shelf = cq.Solid.makeBox(282, 280, 18).translate(cq.Vector(18, 0, 200))
        panels = [_panel('s', side, 18), _panel('p', shelf, 18)]
        contacts, _ = pw.find_contacts(panels)
        contacts[0]['joint'] = 'blind'
        plain = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method='cnc', fit=.1, tool=0))
        bones = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method='cnc', fit=.1, tool=6))
        self.assertLess(bones['s'].Volume(), plain['s'].Volume() - 1)            # „psie kości” w narożnikach gniazd
        self.assertTrue(any(e.geomType() == 'CIRCLE' for e in bones['s'].Edges()))
        self.assertAlmostEqual(bones['s'].intersect(bones['p']).Volume(), 0, 3)
        flat, t = pw.flat_part(bones['s'], 18)
        union, pockets = pw.part_layers(flat, t)
        self.assertTrue(pockets)
        self.assertTrue(all(abs(d - 9.05) < 1e-6 for d, *_ in pockets))       # połowa grubości + luz na dnie

    def test_cross_halving(self):
        a = cq.Solid.makeBox(400, 18, 200).translate(cq.Vector(0, 100, 0))
        b = cq.Solid.makeBox(18, 300, 200).translate(cq.Vector(150, 0, 0))
        panels = [_panel('a', a, 18), _panel('b', b, 18)]
        contacts, _ = pw.find_contacts(panels)
        contacts[0]['joint'] = 'halving'
        out = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method='laser', fit=0))
        self.assertAlmostEqual(a.Volume() - out['a'].Volume(), 18 * 18 * 100, 3)   # nacięcie do połowy wysokości
        self.assertAlmostEqual(out['a'].intersect(out['b']).Volume(), 0, 3)

    def test_between_panels_and_count(self):
        a = cq.Solid.makeBox(18, 300, 400)
        b = cq.Solid.makeBox(18, 300, 400).translate(cq.Vector(318, 0, 0))
        fa = next(f for f in a.Faces() if abs(f.Center().x - 18) < 1e-6)
        fb = next(f for f in b.Faces() if abs(f.Center().x - 318) < 1e-6)
        shapes, info = pw.between_panels(fa, fa.Center().toTuple(), (1, 0, 0), fb, fb.Center().toTuple(), 18, 100)
        bb = shapes[0].BoundingBox()
        self.assertTrue(np.allclose((bb.xmin, bb.xmax, bb.zmin, bb.zmax, bb.ylen), (18, 318, 100, 118, 300)))
        shapes, info = pw.between_panels(fa, fa.Center().toTuple(), (1, 0, 0), fb, fb.Center().toTuple(), 18, None, 3)
        zs = sorted(s.BoundingBox().zmin for s in shapes)
        gaps = np.diff([0, *zs, 400 - 18])
        self.assertTrue(np.allclose(gaps[1:-1], gaps[1], atol=1e-6) and len(shapes) == 3)   # równe odstępy
        shapes, _ = pw.between_panels(fa, fa.Center().toTuple(), (1, 0, 0), fb, fb.Center().toTuple(), 18, 50, 1, True)
        self.assertAlmostEqual(shapes[0].BoundingBox().ylen, 18)                # pionowa przegroda
        with self.assertRaises(k.CadError):
            pw.between_panels(fa, fa.Center().toTuple(), (-1, 0, 0), fb, fb.Center().toTuple(), 18, 0)    # druga ściana za pierwszą

    def test_dxf_and_stl_export(self):
        import ezdxf
        base, walls = _box(4.0)
        panels = [_panel('base', base, 4)] + [_panel(f'w{i}', w, 4) for i, w in enumerate(walls)]
        contacts, _ = pw.find_contacts(panels)
        for c in contacts:
            c['joint'] = pw.joint_for('laser', c['kind'])
        out = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method='laser'))
        parts = [dict(name=p['id'], flat=pw.flat_part(out[p['id']], 4)[0], t=4.0) for p in panels]
        for part in parts:
            bb = part['flat'].BoundingBox()
            self.assertAlmostEqual(bb.zmin, 0, 6)
            self.assertAlmostEqual(bb.zlen, 4, 6)                                 # płasko, grubość wzdłuż Z
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, 'plyty.dxf')
        pw.export_dxf(parts, path, 'laser', True, 600, .2)
        doc = ezdxf.readfile(path)
        layers = {e.dxf.layer for e in doc.modelspace()}
        self.assertEqual(layers, {'CUT', 'OPIS'})                                # laser: tylko przelot i opisy
        texts = sorted(e.dxf.text for e in doc.modelspace() if e.dxftype() == 'TEXT')
        self.assertEqual(texts, sorted(p['id'] for p in panels))
        files = pw.export_stl(parts, os.path.join(folder, 'stl'))
        self.assertEqual(len(files), 5)
        self.assertTrue(all(f.exists() and f.stat().st_size > 0 for f in files))

    def test_history_runners_rebuild(self):
        sk = Body('Szkic', k.sketch('rectangle', 'XY', 200, 150), 'sketch', 'XY').prepared()
        recipe = dict(type='ply_panel', profiles=[{'k': 'sketch', 'id': sk.id}], d=6.0, t=6.0, method='laser', spent=[sk.id], out=['p1'])
        bodies = hist.run_recipe([sk], recipe)
        base = bodies[-1]
        self.assertTrue(pw.is_panel(base) and base.name == 'Płyta 1' and not bodies[0].visible)
        tops = [i for i, e in enumerate(base.shape.Edges()) if abs(e.Center().z - 6) < 1e-6]
        wall = dict(type='ply_wall', base=base.id, edges=hist.edge_refs(base.shape, tops), t=6.0, h=60.0, side='on', flip=False, method='laser', out=['a', 'b', 'c', 'd'])
        bodies = hist.run_recipe(bodies, wall)
        walls = [b for b in bodies if b.name.startswith('Ścianka')]
        self.assertEqual(len(walls), 4)
        self.assertEqual(sorted(round(b.shape.Volume()) for b in walls), [138*60*6] * 2 + [200*60*6] * 2)
        ids = [b.id for b in bodies if pw.is_panel(b)]
        joints = dict(type='ply_joints', ids=ids, joints={}, params=dict(method='laser', fit=0))
        joined = hist.run_recipe(bodies, joints)
        panels = [b for b in joined if pw.is_panel(b)]
        self.assertTrue(all(b.meta['ply']['joined'] for b in panels))
        self.assertEqual(_overlaps([b.shape for b in panels]), 0)
        self.assertEqual(hist.reads(joints, bodies), set(ids))
        self.assertEqual(hist.step_label(dict(label='Ścianka', op=wall)), 'Ścianka ×4 60 mm')
        moved = panels[0].placed(panels[0].shape.translate(cq.Vector(5, 0, 0)), np.column_stack([np.eye(3), [5, 0, 0]]))
        self.assertTrue(pw.is_panel(moved))                                     # przesunięta płyta zostaje płytą


class PlywoodWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from rccad.studio import StudioWindow
        self.w = StudioWindow()
        self.w.resize(1400, 900)
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.wait()
        self.w.document._saved_revision = self.w.document._revision
        self.w.close()
        self.w.deleteLater()
        from PySide6.QtCore import QEvent
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def wait(self, limit=120):
        end = time.monotonic() + limit
        while (self.w.busy or any(st['running'] or st['pending'] for st in self.w._pv.values()) or getattr(self.w, '_exports', 0)) and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()

    def test_tab_tools_and_full_flow(self):
        from rccad.studio import TABS, TAB_OF
        w = self.w
        self.assertEqual(TABS['Sklejka'], ['ply', 'ply_wall', 'ply_between', 'ply_joints', 'ply_cut'])
        self.assertEqual(TAB_OF['ply_joints'], 'Sklejka')
        sk = Body('Szkic', k.sketch('rectangle', 'XY', 200, 150), 'sketch', 'XY').prepared()
        w.document.commit([sk])
        w.refresh()
        # płyta ze szkicu: metoda i grubość wspólne dla paneli, zapamiętane w ustawieniach
        w.toggle_mode('ply')
        self.assertTrue(w.ply_panel.isVisible())
        seg = w._ply_widgets[0][0]
        seg.setCurrentIndex(seg.findData('cnc'))
        w._ply_widgets[0][1].setValue(17)
        w._ply_widgets[0][1].setValue(18)
        self.assertEqual(w._ply_widgets[1][1].value(), 18)                     # Ścianka ma tę samą grubość
        self.assertEqual(w._read_settings('plywood')['t']['cnc'], 18)
        with patch.object(w, '_profile_at', return_value=w._sketch_profile(sk)):
            w.view_clicked(5, 5, False, False)
        self.assertTrue(w.view.preview_items)
        w.apply_ply_panel()
        self.wait()
        base = next(b for b in w.document.bodies if pw.is_panel(b))
        self.assertEqual((base.name, base.meta['ply']['t'], base.meta['ply']['method']), ('Płyta 1', 18.0, 'cnc'))
        self.assertAlmostEqual(base.shape.Volume(), 200 * 150 * 18)
        # ścianki: Shift dodaje krawędzie, strzałka zmienia wysokość
        w.toggle_mode('ply_wall')
        tops = [i for i, e in enumerate(base.shape.Edges()) if abs(e.Center().z - 18) < 1e-6]
        for n, i in enumerate(tops):
            with patch.object(w.view, 'nearest_edge', return_value=(base.id, i)):
                w.view_clicked(5, 5, n > 0, False)
        self.assertEqual(len(w.pw_edges), 4)
        self.assertEqual([h['id'] for h in w.view.handles], ['plyH'])
        w.handle_dragged('plyH', 20)
        w.handle_released('plyH')
        self.assertAlmostEqual(w.pw_height.value(), 100)
        w.apply_ply_wall()
        self.wait()
        walls = [b for b in w.document.bodies if b.name.startswith('Ścianka')]
        self.assertEqual(sorted(round(b.shape.Volume()) for b in walls), [114 * 100 * 18] * 2 + [200 * 100 * 18] * 2)
        # półka między dłuższymi ściankami: przycięta do wnętrza, strzałka położenia
        ys = sorted([b for b in walls if b.shape.BoundingBox().ylen < 19], key=lambda b: b.shape.Center().y)
        fa = max((f for f in ys[0].shape.Faces() if f.normalAt().y > .99), key=lambda f: f.Area())
        fb = max((f for f in ys[1].shape.Faces() if f.normalAt().y < -.99), key=lambda f: f.Area())
        w.toggle_mode('ply_between')
        with patch.object(w.view, 'pick_face', return_value=(ys[0].id, np.array([0, 1., 0]), np.array(fa.Center().toTuple()))):
            w.view_clicked(5, 5, False, False)
        with patch.object(w.view, 'pick_face', return_value=(ys[1].id, np.array([0, -1., 0]), np.array(fb.Center().toTuple()))):
            w.view_clicked(5, 5, False, False)
        self.assertEqual([h['id'] for h in w.view.handles], ['plyP'])
        self.assertIn('głębokość 164.0', w.pb_status.text())                  # między krótszymi ściankami
        w.apply_ply_between()
        self.wait()
        shelf = next(b for b in w.document.bodies if b.name == 'Półka 1')
        self.assertAlmostEqual(shelf.shape.Volume(), 164 * 114 * 18)
        # połączenia: wykrycie, zmiana metody zamienia niedostępne, podgląd i zapis kroku
        w.toggle_mode('ply_joints')
        self.assertEqual(sorted(c['kind'] for c in w.pj_contacts), ['L'] * 8 + ['T'] * 4)
        key = next(c['key'] for c in w.pj_contacts if c['kind'] == 'T')
        combo = w.pj_rows[key][1]
        combo.setCurrentIndex(combo.findData('groove'))
        w.pj_method.setCurrentIndex(w.pj_method.findData('laser'))
        self.assertEqual(next(c['joint'] for c in w.pj_contacts if c['key'] == key), 'tab')   # rowek -> czopy przelotowe
        self.assertFalse(combo.model().item(combo.findData('blind')).isEnabled())
        w.update_ply_joints_preview()
        self.wait()
        self.assertTrue(w.override)
        w.apply_ply_joints()
        self.wait()
        self.assertEqual(w.document.info['op']['type'], 'ply_joints')
        panels = [b for b in w.document.bodies if pw.is_panel(b)]
        self.assertEqual(len(panels), 6)
        self.assertTrue(all(b.meta['ply']['method'] == 'laser' for b in panels))
        self.assertEqual(_overlaps([b.shape for b in panels]), 0)
        # do cięcia: lista i zapis DXF w tle
        w.toggle_mode('ply_cut')
        self.assertIn('Płyta 1', w.pc_list.text())
        self.assertIn('6 płyt', w.pc_status.text())
        path = os.path.join(tempfile.mkdtemp(), 'plyty.dxf')
        w.ply_export(path)
        self.wait()
        self.assertTrue(os.path.exists(path))
        w.undo()
        self.wait()
        self.assertFalse(any(b.meta['ply'].get('joined') for b in w.document.bodies if pw.is_panel(b)))


if __name__ == '__main__':
    unittest.main()
