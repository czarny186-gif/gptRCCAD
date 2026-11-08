"""Zakładka Sklejka: płyty, ścianki, półki, rozpoznawanie styków, połączenia zależne od metody produkcji, pliki do cięcia."""
import math
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


class PlywoodPolygonTests(unittest.TestCase):
    """0.4.60: ścianki na podstawie-wielokącie schodzą się na skos, wczepy w takich narożnikach, grupa pudełka."""

    def _walls(self, base, side):
        b = Body('Płyta 1', base, meta=pw.ply_meta(6, 'laser')).prepared()
        tops = [i for i, e in enumerate(base.Edges()) if abs(e.Center().z - 6) < 1e-6]
        return hist.run_recipe([b], dict(type='ply_wall', base=b.id, edges=hist.edge_refs(base, tops), t=6.0, h=60.0, side=side,
                                         flip=False, method='laser', out=[f'w{i}' for i in tops]))

    def test_polygon_walls_meet_on_mitre_without_overlap_or_gap(self):
        hexagon = cq.Workplane().polygon(6, 200).extrude(6).val()
        for side in ('on', 'side'):
            bodies = self._walls(hexagon, side)
            walls = [b for b in bodies if b.name.startswith('Ścianka')]
            self.assertEqual(len(walls), 6)
            self.assertEqual(_overlaps([b.shape for b in bodies]), 0, side)
            vols = sorted(round(w.shape.Volume(), 1) for w in walls)
            self.assertAlmostEqual(vols[0], vols[-1], 1)                           # wszystkie jednakowe (symetryczne skosy)
            ring = kernel_union([w.shape for w in walls])
            self.assertEqual(len(ring.Solids()), 1, side)                          # ścianki stykają się w narożnikach - bez szczelin
            self.assertEqual({b.folder for b in bodies}, {'Pudełko 1'})            # podstawa i ścianki w jednej grupie
            outer = 100 if side == 'on' else 100 + 6 / math.cos(math.radians(30))
            bb = ring.BoundingBox()
            self.assertAlmostEqual(bb.xlen, 2 * outer, 3)                          # przy boku: na zewnątrz podstawy, narożniki pełne

    def test_rectangle_side_mode_fills_corners(self):
        bodies = self._walls(cq.Solid.makeBox(200, 150, 6), 'side')
        walls = [b.shape for b in bodies if b.name.startswith('Ścianka')]
        ring = kernel_union(walls)
        self.assertAlmostEqual(ring.Volume(), (212 * 162 - 200 * 150) * 66, 0)  # pełny obwód razem z narożnikami
        self.assertEqual(_overlaps([b.shape for b in bodies]), 0)

    def test_mitre_contacts_get_fingers(self):
        bodies = self._walls(cq.Workplane().polygon(5, 200).extrude(6).val(), 'on')
        panels = pw.panels_of(bodies)
        contacts, skipped = pw.find_contacts(panels)
        self.assertEqual(sorted(c['kind'] for c in contacts), ['L'] * 5 + ['M'] * 5)
        self.assertFalse(skipped)
        mitre = next(c for c in contacts if c['kind'] == 'M')
        self.assertAlmostEqual(180 - mitre['angle'], 108, 1)                        # narożnik pięciokąta
        self.assertEqual(pw.joint_for('laser', 'M'), 'finger')
        for c in contacts:
            c['joint'] = 'finger'
        before = {p['id']: p['shape'].Volume() for p in panels}
        out = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method='print', fit=.2))
        shapes = [out[p['id']] for p in panels]
        self.assertTrue(all(s.isValid() and len(s.Solids()) == 1 for s in shapes))
        self.assertEqual(_overlaps(shapes), 0)
        wall = next(p['id'] for p in panels if p['id'] != bodies[0].id)
        self.assertNotAlmostEqual(out[wall].Volume(), before[wall], 0)
        flat, t = pw.flat_part(out[wall], 6)
        self.assertAlmostEqual(t, 6)

    def test_laser_polygon_corners_are_cut_square(self):
        """Laser / frezarka: narożnik pod kątem z końcami prostopadłymi do płyt - na przemian jedna ścianka dochodzi
        do zewnętrznego wierzchołka, druga jest cofnięta (jak w przykładowym modelu); wszystkie ściany płyt równoległe
        albo prostopadłe do ich stron - da się je wyciąć laserem."""
        bodies = self._walls(cq.Workplane().polygon(6, 115.47).extrude(6).val(), 'on')
        panels = pw.panels_of(bodies)
        contacts, _ = pw.find_contacts(panels)
        for c in contacts:
            c['joint'] = pw.joint_for('laser', c['kind'])
        out = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method='laser', fit=0.1))
        shapes = [out[p['id']] for p in panels]
        self.assertEqual(_overlaps(shapes), 0)
        for p, shape in zip(panels, shapes):
            n = pw.panel_info(shape, 6)['n']
            for f in shape.Faces():
                self.assertEqual(f.geomType(), 'PLANE')
                fn = np.array(f.normalAt().toTuple())
                self.assertTrue(abs(abs(fn @ n) - 1) < 1e-6 or abs(fn @ n) < 1e-6, p['name'])   # bez skosów
        # zewnętrzny wierzchołek narożnika: na każdej wysokości dochodzi do niego dokładnie jedna ścianka
        walls = [out[p['id']] for p in panels if p['id'] != bodies[0].id]
        vertex = cq.Vector(57.735, 0, 0)
        for z in np.linspace(9, 60, 9):
            probe = cq.Vertex.makeVertex(vertex.x - .05, vertex.y, z)
            near = [w for w in walls if w.distance(probe) < .2]
            self.assertLessEqual(len(near), 1)
        flat, t = pw.flat_part(walls[0], 6)
        union, pockets = pw.part_layers(flat, t)
        self.assertEqual(pockets, [])                                             # laser: tylko cięcie na wylot
        # bez połączenia (laser): jedna ścianka zachodzi na całej wysokości, nadal bez skosów
        for c in contacts:
            if c['kind'] == 'M':
                c['joint'] = 'none'
        out = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method='laser', fit=0.1))
        self.assertEqual(_overlaps([out.get(p['id'], p['shape']) for p in panels]), 0)

    def test_drawing_parts_laid_out_without_overlap(self):
        from rccad import drawing as dr
        bodies = self._walls(cq.Solid.makeBox(200, 150, 6), 'on')
        items = [(b.name, b.shape, 6.0) for b in bodies]
        flat, parts = pw.drawing_parts(items)
        self.assertEqual(len(parts), 5)
        for i, a in enumerate(parts):
            for b in parts[i + 1:]:
                self.assertTrue(a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])   # części obok siebie
        source = dr.DrawingSource(flat, 'Pudełko', parts=parts, iso_shape=kernel_union([b.shape for b in bodies]))
        d = dr.build_drawing(source, views=('top', 'iso'))
        texts = [p.text for p in d.prims if isinstance(p, dr.Label)]
        for name in ('Płyta 1', 'Ścianka 1', 'Ścianka 4'):
            self.assertIn(name, texts)
        self.assertIn('200', texts)
        self.assertIn('60', texts)                                                  # wymiary każdej płyty


def kernel_union(shapes):
    out = shapes[0]
    for s in shapes[1:]:
        out = out.fuse(s)
    return out.clean()


class PlywoodCrossTests(unittest.TestCase):
    """0.4.62: przegrody na krzyż od razu z nacięciami; płyty ukryte są dla nowych płyt niewidoczne."""

    def _box(self):
        t = 18.0
        base = cq.Solid.makeBox(400, 300, t)
        b = Body('Płyta 1', base, meta=pw.ply_meta(t, 'cnc')).prepared()
        tops = [i for i, e in enumerate(base.Edges()) if abs(e.Center().z - t) < 1e-6]
        return hist.run_recipe([b], dict(type='ply_wall', base=b.id, edges=hist.edge_refs(base, tops), t=t, h=200.0, side='on', flip=False,
                                         method='cnc', out=['w1', 'w2', 'w3', 'w4']))

    def _divider(self, bodies, axis, out, ignore=()):
        walls = [x for x in bodies if x.name.startswith('Ścianka')]
        pair = sorted([w for w in walls if (w.shape.BoundingBox().xlen if axis == 0 else w.shape.BoundingBox().ylen) < 19],
                      key=lambda w: w.shape.Center().toTuple()[axis])
        face = lambda body, sign: max((f for f in body.shape.Faces() if f.geomType() == 'PLANE' and np.array(f.normalAt().toTuple())[axis] * sign > .99),
                                      key=lambda f: f.Area())
        ref = lambda body, f: dict(hist.face_ref(f, np.array(f.normalAt().toTuple()), np.array(f.Center().toTuple()), body.shape), id=body.id)
        recipe = dict(type='ply_between', a=ref(pair[0], face(pair[0], 1)), b=ref(pair[1], face(pair[1], -1)), t=18.0, pos=None, count=1,
                      turn=True, method='cnc', out=[out], ignore=list(ignore))
        return hist.run_recipe(bodies, recipe)

    def test_crossing_dividers_get_halving_automatically(self):
        bodies = self._divider(self._box(), 0, 'd1')
        d1 = next(x for x in bodies if x.id == 'd1')
        bodies = self._divider(bodies, 1, 'd2')
        n1, n2 = next(x for x in bodies if x.id == 'd1'), next(x for x in bodies if x.id == 'd2')
        self.assertLess(n1.shape.Volume(), d1.shape.Volume() - 18 * 18 * 99)      # nacięcie do połowy w istniejącej przegrodzie
        self.assertEqual(len(n2.shape.Solids()), 1)                                  # nowa przechodzi przez całą szerokość
        self.assertAlmostEqual(n1.shape.intersect(n2.shape).Volume(), 0, 3)
        self.assertEqual((n1.meta['ply']['joined'], n2.meta['ply']['joined']), (['d2'], ['d1']))
        contacts, _ = pw.find_contacts(pw.panels_of(bodies))
        self.assertFalse(any(c['kind'] == 'X' for c in contacts))                   # już połączone - nie wraca w Połączeniach

    def test_hidden_panels_are_invisible_for_new_ones(self):
        bodies = self._divider(self._box(), 0, 'd1')
        d1 = next(x for x in bodies if x.id == 'd1')
        bodies = self._divider(bodies, 1, 'd2', ignore=['d1'])
        n1, n2 = next(x for x in bodies if x.id == 'd1'), next(x for x in bodies if x.id == 'd2')
        self.assertAlmostEqual(n1.shape.Volume(), d1.shape.Volume(), 3)            # ukryta płyta nietknięta
        self.assertAlmostEqual(n2.shape.Volume(), 264 * 200 * 18, 0)               # nowa - jakby ukrytej nie było
        self.assertFalse(n2.meta['ply'].get('joined'))


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
        w.objects_hide(shelf.id)                                                  # ukryta płyta: nowe płyty jej nie widzą
        self.assertEqual(w._ply_hidden(), [shelf.id])
        w.set_mode('ply_between')
        with patch.object(w.view, 'pick_face', return_value=(ys[0].id, np.array([0, 1., 0]), np.array(fa.Center().toTuple()))):
            w.view_clicked(5, 5, False, False)
        with patch.object(w.view, 'pick_face', return_value=(ys[1].id, np.array([0, -1., 0]), np.array(fb.Center().toTuple()))):
            w.view_clicked(5, 5, False, False)
        self.assertEqual(w._pb_recipe()['ignore'], [shelf.id])
        self.assertNotIn('W tym miejscu', w.pb_status.text())                   # w tym samym miejscu - bez błędu, bo ukrytej „nie ma”
        w.set_mode(None)
        w.objects_hide(shelf.id)
        # połączenia: wykrycie, zmiana metody zamienia niedostępne, podgląd i zapis kroku
        w.toggle_mode('ply_joints')
        self.assertIn('Szukam', w.pj_status.text())                            # styki liczone w tle - okno nie czeka
        self.wait()
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
        self.assertEqual({b.folder for b in panels}, {'Pudełko 1'})            # całe pudełko w jednej grupie
        w.toggle_mode('ply_cut')
        self.assertIn('Płyta 1', w.pc_list.text())
        self.assertIn('6 płyt', w.pc_status.text())
        w.pc_scope.setCurrentIndex(1)                                          # tylko zaznaczone
        with patch.object(w.view, 'pick_body', return_value=shelf.id):
            w.view_clicked(5, 5, False, False)
        self.assertEqual([b.id for b in w._pc_bodies()], [shelf.id])
        self.assertIn('1 płyt', w.pc_status.text())
        w.pc_scope.setCurrentIndex(0)
        self.assertEqual(len(w._pc_bodies()), 6)
        path = os.path.join(tempfile.mkdtemp(), 'plyty.dxf')
        w.ply_export(path)
        self.wait()
        self.assertTrue(os.path.exists(path))
        # rysunek płyt: wszystkie płyty grupy rozłożone obok siebie
        from rccad.studio import TABS as T
        self.assertIn('plydrawing', T['Rysunek'])
        w.toggle_mode('plydrawing')
        with patch.object(w.view, 'pick_face', return_value=(shelf.id, np.array([0, 0, 1.]), np.array([100, 75, 50.]))):
            w.view_clicked(5, 5, False, False)
        self.wait()
        win = w._drawing_windows[-1]
        self.assertEqual(len(win.source.parts), 6)
        self.assertIn('Pudełko 1', win.windowTitle())
        win.close()
        w.undo()
        self.wait()
        self.assertFalse(any(b.meta['ply'].get('joined') for b in w.document.bodies if pw.is_panel(b)))


if __name__ == '__main__':
    unittest.main()
