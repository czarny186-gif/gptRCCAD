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

    def test_concave_base_every_wall_gets_fingers(self):
        """0.4.63 (model użytkownika): podstawa-wielokąt wklęsły - ścianki przy wklęsłym narożniku też łączą się z podstawą
        (podstawa sięga po obu stronach ich płaszczyzny, a styk i tak jest wykryty)."""
        pts = [(-480, 0), (-140, -40), (-20, -240), (212.5, -214.9), (222.6, -67.9), (20, 200), (-327.4, 206.1)]
        base = cq.Workplane().polyline(pts).close().extrude(2).val()
        for side in ('side', 'on'):
            b = Body('Płyta 1', base, meta=pw.ply_meta(2, 'laser')).prepared()
            tops = [i for i, e in enumerate(base.Edges()) if abs(e.Center().z - 2) < 1e-6]
            bodies = hist.run_recipe([b], dict(type='ply_wall', base=b.id, edges=hist.edge_refs(base, tops), t=2.0, h=20.0,
                                               side=side, flip=False, method='laser', out=[f'w{i}' for i in tops]))
            panels = pw.panels_of(bodies)
            contacts, skipped = pw.find_contacts(panels)
            walls = {x.id for x in bodies if x.id != b.id}
            on_base = {c['b'] if c['a'] == b.id else c['a'] for c in contacts if b.id in (c['a'], c['b'])}
            self.assertEqual(on_base, walls, side)                                 # każda ścianka styka się z podstawą
            self.assertFalse(skipped)
            for c in contacts:
                c['joint'] = pw.joint_for('laser', c['kind'])
            failures = []
            out = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method='laser', fit=.1),
                                  failures=failures)
            self.assertEqual(failures, [], side)
            self.assertEqual(set(out), walls | {b.id})
            self.assertEqual(_overlaps([out[p['id']] for p in panels]), 0, side)

    def test_acute_corners_nothing_sticks_out(self):
        """0.4.65 (model użytkownika): w narożniku o kącie ostrym ścianka z końcem prostopadłym nie wystaje poza
        sąsiednią; ostry trójkąt, wklęsły narożnik prosty („Przy boku”) i ścianki prawie w jednej linii też poprawnie."""
        import uuid
        cases = [([(-46, 0), (-46, -25), (-22.589, -14.389), (15, -31), (22.589, -14.389), (22.589, 14.389), (-22.589, 14.389)], 2.0),
                 ([(0, 0), (80, 0), (20, 40)], 2.0),
                 ([(0, 0), (60, 0), (60, 20), (30, 20), (30, 50), (0, 50)], 3.0),
                 ([(25.41, 8.4), (7.7, 38.0), (-5.8, -39.14), (21.18, -19.02), (37.97, -14.28)], 3.0)]
        for pts, t in cases:
            for meth, side in (('laser', 'on'), ('laser', 'side'), ('cnc', 'side'), ('print', 'on')):
                base = cq.Workplane().polyline(pts).close().extrude(t).val()
                b = Body('Płyta 1', base, meta=pw.ply_meta(t, meth)).prepared()
                tops = [i for i, e in enumerate(base.Edges()) if abs(e.Center().z - t) < 1e-6]
                bodies = hist.run_recipe([b], dict(type='ply_wall', base=b.id, edges=hist.edge_refs(base, tops), t=t, h=12.0, side=side,
                                                   flip=False, method=meth, out=[uuid.uuid4().hex for _ in tops]))
                panels = pw.panels_of(bodies)
                contacts, skipped = pw.find_contacts(panels)
                self.assertFalse(skipped, (pts, meth, side))
                for c in contacts:
                    c['joint'] = pw.joint_for(meth, c['kind'])
                failures = []
                out = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method=meth, fit=.1, tool=0),
                                      failures=failures)
                self.assertEqual(failures, [], (pts, meth, side))
                shapes = [out.get(p['id'], p['shape']) for p in panels]
                self.assertEqual(_overlaps(shapes), 0, (pts, meth, side))
                outline = cq.Workplane().polyline(pts).close().val()
                if side == 'side':
                    outline = outline.offset2D(t, 'intersection')[0]
                prism = cq.Solid.extrudeLinear(cq.Face.makeFromWires(outline).translate(cq.Vector(0, 0, -5)), cq.Vector(0, 0, 40))
                self.assertLess(sum(s.cut(prism).Volume() for s in shapes), 1e-3, (pts, meth, side))   # nic nie wystaje

    def test_laser_polygon_box_exports_with_kerf(self):
        """0.4.63: Do cięcia - podstawa-wielokąt z wczepami eksportuje się także z kompensacją lasera (offset2D bywał pusty)."""
        bodies = self._walls(cq.Workplane().polygon(6, 200).extrude(6).val(), 'on')
        panels = pw.panels_of(bodies)
        contacts, _ = pw.find_contacts(panels)
        for c in contacts:
            c['joint'] = pw.joint_for('laser', c['kind'])
        out = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method='laser', fit=0.1))
        parts = [dict(name=p['name'], flat=pw.flat_part(out[p['id']], 6)[0], t=6.0) for p in panels]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'box.dxf')
            pw.export_dxf(parts, path, 'laser', True, 1200, kerf=0.15)
            self.assertGreater(os.path.getsize(path), 1000)

    def test_failed_contact_is_skipped_and_reported(self):
        """0.4.63: nieudane połączenie nie psuje pozostałych - jest pomijane i zgłaszane."""
        bodies = self._walls(cq.Solid.makeBox(200, 150, 6), 'on')
        panels = pw.panels_of(bodies)
        contacts, _ = pw.find_contacts(panels)
        for c in contacts:
            c['joint'] = 'finger'
        bad = contacts[0]
        failures = []
        bad['joint'] = 'blind'                                                      # niedostępne dla lasera -> błąd tylko tego styku
        out = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method='laser', fit=0.1),
                              failures=failures)
        self.assertEqual(len(failures), 1)
        self.assertTrue(all(s.isValid() for s in out.values()))
        changed = [p for p in panels if abs(out[p['id']].Volume() - p['shape'].Volume()) > 1]
        self.assertGreaterEqual(len(changed), 4)
        with self.assertRaises(Exception):
            pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, [bad], dict(method='laser', fit=0.1))

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
        self.assertEqual(TABS['Sklejka'], ['ply', 'ply_wall', 'ply_between', 'ply_joints', 'ply_cut', 'ply_unfold', 'ply_fold'])
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


class PlywoodStepEditTests(PlywoodWindowTests):
    """0.5.1: dwuklik w krok Płyty / Ścianki / Połączeń otwiera to samo narzędzie z wyborem i wartościami z kroku."""

    def test_panel_wall_and_joints_steps_reopen_prefilled(self):
        w = self.w
        sk = Body('Szkic', k.sketch('rectangle', 'XY', 200, 150), 'sketch', 'XY').prepared()
        w.document.commit([sk]); w.refresh()
        w.toggle_mode('ply')
        w._ply_widgets[0][1].setValue(18)
        with patch.object(w, '_profile_at', return_value=w._sketch_profile(sk)):
            w.view_clicked(5, 5, False, False)
        w.apply_ply_panel(); self.wait()
        base = next(b for b in w.document.bodies if pw.is_panel(b))
        w.toggle_mode('ply_wall')
        tops = [i for i, e in enumerate(base.shape.Edges()) if abs(e.Center().z - 18) < 1e-6]
        for n, i in enumerate(tops):
            with patch.object(w.view, 'nearest_edge', return_value=(base.id, i)):
                w.view_clicked(5, 5, n > 0, False)
        w.pw_height.setValue(80); w.apply_ply_wall(); self.wait()
        w.set_mode(None)
        w.toggle_mode('ply_joints'); self.wait()
        key = next(c['key'] for c in w.pj_contacts)
        combo = w.pj_rows[key][1]
        options = [combo.itemData(i) for i in range(combo.count()) if combo.model().item(i).isEnabled()]
        choice = next(o for o in options if o != w.pj_contacts[0]['joint'])
        combo.setCurrentIndex(combo.findData(choice))
        w.apply_ply_joints(); self.wait(); w.set_mode(None)
        doc = w.document
        infos = doc.infos()[0]; count = len(infos)
        kinds = [(i.get('op') or {}).get('type') for i in infos]
        # Ścianka: krawędzie i wysokość z kroku
        w.history_edit(kinds.index('ply_wall')); self.app.processEvents()
        self.assertEqual(w.mode, 'ply_wall'); self.assertEqual(len(w.pw_edges), 4); self.assertAlmostEqual(w.pw_height.value(), 80)
        w.pw_height.setValue(60); w.apply_ply_wall(); self.wait(); self.wait()
        infos = doc.infos()[0]
        self.assertEqual(len(infos), count); self.assertAlmostEqual(infos[kinds.index('ply_wall')]['op']['h'], 60)
        self.assertFalse(any(i.get('stale') for i in infos),[(i['label'],i.get('why')) for i in infos if i.get('stale')])
        # Połączenia: wybrane rodzaje połączeń z kroku
        w.history_edit(kinds.index('ply_joints')); self.wait()
        self.assertEqual(w.mode, 'ply_joints')
        self.assertEqual(next(c['joint'] for c in w.pj_contacts if c['key'] == key), choice)
        w.set_mode(None); self.app.processEvents(); self.wait()
        # Płyta: profile z kroku, Zastosuj bez nowego wyboru zastępuje krok
        w.history_edit(kinds.index('ply_panel')); self.app.processEvents()
        self.assertEqual(w.mode, 'ply')
        w.apply_ply_panel(); self.wait(); self.wait()
        self.assertEqual(len(doc.infos()[0]), count)
        self.assertFalse(any(i.get('stale') for i in doc.infos()[0]))


class PlywoodFoldTests(PlywoodWindowTests):
    """0.4.64: Rozłóż / Złóż płyty - pamięć w płytach, przesunięcie, biblioteka; frez i narożniki gniazd."""

    def _box(self):
        import uuid
        base = cq.Solid.makeBox(200, 150, 6)
        b = Body('Płyta 1', base, meta=pw.ply_meta(6, 'laser')).prepared()
        tops = [i for i, e in enumerate(base.Edges()) if abs(e.Center().z - 6) < 1e-6]
        return hist.run_recipe([b], dict(type='ply_wall', base=b.id, edges=hist.edge_refs(base, tops), t=6.0, h=60.0, side='on',
                                         flip=False, method='laser', out=[uuid.uuid4().hex for _ in tops]))

    def test_tab_tools_and_full_flow(self):
        pass

    def test_unfold_move_library_fold(self):
        from PySide6.QtCore import Qt
        from rccad import library
        w = self.w
        bodies = [b.prepared() for b in self._box()]
        w.document.commit(bodies)
        w.refresh()
        centres = {b.id: np.array(b.shape.Center().toTuple()) for b in bodies}
        # bez zaznaczenia: wskazanie płyty kliknięciem; cały zestaw (grupa „Pudełko 1”) się rozkłada
        w.selected = []
        w.tools['ply_unfold'].click()
        self.assertEqual(w.mode, 'plyfoldpick')
        with patch.object(w.view, 'pick_body', return_value=bodies[2].id):
            w.view_clicked(5, 5, False, False)
        self.wait()
        flat = [w.document.get(b.id) for b in bodies]
        self.assertTrue(all(abs(b.shape.BoundingBox().zlen - 6) < 1e-6 for b in flat))       # wszystkie leżą płasko
        self.assertEqual(_overlaps([b.shape for b in flat]), 0)
        self.assertEqual(w.document.info['op']['type'], 'ply_fold')
        self.assertTrue(all(b.meta['ply']['fold']['flat'] for b in flat))
        w.tools['ply_unfold'].click(); self.wait()                              # zaznaczone - już rozłożone: komunikat
        # przesunięcie całego rozkładu (narzędziem przesuwania) i zapis do biblioteki
        w.selected = [b.id for b in bodies]
        w.document.commit(hist.run_recipe(w.document.bodies, dict(type='transform', ids=[b.id for b in bodies], v=[300, 0, 0], mode='move',
                                                                  id=bodies[0].id)), label='Przesunięcie', icon='move')
        folder = tempfile.mkdtemp()
        path = library.save_bodies([w.document.get(b.id) for b in bodies], folder, 'Pudełko')
        # złożenie przesuniętego rozkładu: pudełko przesunięte o to samo
        w.selected = [bodies[0].id]
        w.tools['ply_fold'].click(); self.wait()
        for b in bodies:
            got = np.array(w.document.get(b.id).shape.Center().toTuple())
            self.assertTrue(np.allclose(got, centres[b.id] + (300, 0, 0), atol=1e-6), b.name)
        w.undo(); self.wait()
        self.assertTrue(w.document.get(bodies[0].id).meta['ply']['fold']['flat'])
        # wstawienie z biblioteki w innym miejscu: kopia ma własny klucz i składa się w nowym miejscu
        action = dict(bodies=library.load_bodies('object', path), name='Pudełko', dialog=None)
        w._library_insert(action, np.eye(3), np.array([0.0, 500.0, 0.0])); self.wait()
        copies = [b for b in w.document.bodies if b.id not in centres]
        self.assertEqual(len(copies), 5)
        self.assertNotEqual(copies[0].meta['ply']['fold']['key'], w.document.get(bodies[0].id).meta['ply']['fold']['key'])
        w.selected = [copies[0].id]
        w.tools['ply_fold'].click(); self.wait()
        got = sorted(tuple(np.round(w.document.get(c.id).shape.Center().toTuple(), 4)) for c in copies)
        want = sorted(tuple(np.round(c + (300, 500, 0), 4)) for c in centres.values())
        self.assertEqual(got, want)
        self.assertTrue(w.document.get(bodies[0].id).meta['ply']['fold']['flat'])   # oryginał nadal rozłożony

    def test_cnc_tool_warning_and_corner_styles(self):
        w = self.w
        w.toggle_mode('ply_joints')
        w._ply_set_method('cnc')
        w.pj_tool.setValue(6)
        w.pj_contacts = [dict(key='a:b', ta=2.0, tb=2.0, joint='finger', kind='L', a='a', b='b')]
        w._pj_params_changed(save=False)
        self.assertTrue(w.pj_tool_warn.isVisibleTo(w.ply_joints_panel))
        self.assertIn('Ø2', w.pj_tool_fix.text())
        w.pj_tool_fix.click()
        self.assertEqual(w.pj_tool.value(), 2)
        self.assertFalse(w.pj_tool_warn.isVisibleTo(w.ply_joints_panel))
        w.pj_corner.setCurrentIndex(list(pw.CORNERS).index('tbone'))
        self.assertEqual(w._pj_params()['corner'], 'tbone')
        self.assertEqual(w._read_settings('plywood')['corner'], 'tbone')
        w.pj_contacts = []
        w.set_mode(None)


class PlywoodInsertTests(PlywoodWindowTests):
    """0.4.66: Ścianka jak Kołnierz - przycisk Wstaw (czerwony) dodaje ściankę od razu po kliknięciu krawędzi."""

    def test_tab_tools_and_full_flow(self):
        pass

    def test_insert_walls_one_by_one_like_batch(self):
        w = self.w
        hexagon = cq.Workplane().polygon(6, 200).extrude(6).val()
        base = Body('Płyta 1', hexagon, meta=pw.ply_meta(6, 'laser')).prepared()
        w.document.commit([base])
        w.refresh()
        w.toggle_mode('ply_wall')
        w._ply_set_method('laser')
        w._ply_widgets[0][1].setValue(6)
        w.pw_height.setValue(60)
        self.assertFalse(w.pw_armed)
        w.pw_insert.click()
        self.assertTrue(w.pw_armed)
        tops = [i for i, e in enumerate(hexagon.Edges()) if abs(e.Center().z - 6) < 1e-6]
        for i in tops:
            with patch.object(w.view, 'nearest_edge', return_value=(base.id, i)):
                w.view_clicked(5, 5, False, False)
            self.wait()
        self.assertEqual(w.mode, 'ply_wall')
        walls = [b for b in w.document.bodies if b.name.startswith('Ścianka')]
        self.assertEqual(len(walls), 6)
        self.assertEqual(_overlaps([b.shape for b in w.document.bodies]), 0)
        batch = PlywoodPolygonTests._walls(None, hexagon, 'on')
        want = sorted(round(b.shape.Volume(), 2) for b in batch if b.name.startswith('Ścianka'))
        self.assertEqual(sorted(round(b.shape.Volume(), 2) for b in walls), want)        # jak dodane naraz (skosy w narożnikach)
        self.assertEqual({b.folder for b in w.document.bodies}, {'Pudełko 1'})
        w.pw_insert.click()
        self.assertFalse(w.pw_armed)
        with patch.object(w.view, 'nearest_edge', return_value=(base.id, tops[0])):
            w.view_clicked(5, 5, False, False)                  # wyłączone: tylko wybór krawędzi
        self.wait()
        self.assertEqual(len([b for b in w.document.bodies if b.name.startswith('Ścianka')]), 6)
        self.assertEqual(w.pw_edges, [tops[0]])


class SheetTabWallTests(PlywoodWindowTests):
    """0.4.66: Blacha - kołnierz na noski: ścianki bez gięcia połączone noskami, wymiary jak przy kołnierzu."""

    def test_tab_tools_and_full_flow(self):
        pass

    def _sheet(self, w):
        box = Body('Blacha', k.box(100, 60, 2)).prepared()
        top = max(box.shape.Faces(), key=lambda f: f.Center().z)
        bodies = hist.run_recipe([box], dict(type='sheet', id=box.id, face=hist.face_ref(top, (0, 0, 1), top.Center().toTuple(), box.shape)))
        w.document.commit(bodies)
        w.refresh()
        return bodies[0]

    def _edge(self, body, x, y):
        sh = body.shape
        tops = [i for i, e in enumerate(sh.Edges()) if e.geomType() == 'LINE' and abs(e.startPoint().z - 2) < 1e-6 and abs(e.endPoint().z - 2) < 1e-6]
        return min(tops, key=lambda i: abs(sh.Edges()[i].positionAt(.5).x - x) + abs(sh.Edges()[i].positionAt(.5).y - y))

    def test_tabwalls_box_outer_and_inner(self):
        from rccad.studio import TABS
        w = self.w
        self.assertEqual(TABS['Blacha'][:4], ['sheet', 'flange', 'hem', 'tabwall'])
        for measure, size, height in (('outer', (100, 60), 30), ('inner', (104, 64), 32)):
            w.document = type(w.document)()
            sheet = self._sheet(w)
            w.toggle_mode('tabwall')
            self.assertTrue(w.tabwall_panel.isVisible())
            w.tw_length.setValue(30)
            w.tw_datum.setCurrentIndex(w.tw_datum.findData(measure))
            w.tw_bend.click()
            self.assertTrue(w.tw_armed)
            for x, y in ((50, 0), (100, 30), (50, 60), (0, 30)):
                with patch.object(w.view, 'nearest_edge', return_value=(sheet.id, self._edge(w.document.get(sheet.id), x, y))):
                    w.view_clicked(5, 5, False, False)
                self.wait()
            walls = [b for b in w.document.bodies if b.name.startswith('Ścianka blachy')]
            self.assertEqual(len(walls), 4, measure)
            shapes = [b.shape for b in w.document.bodies]
            self.assertEqual(_overlaps(shapes), 0)
            bb = k.compound(shapes).BoundingBox()
            self.assertAlmostEqual(bb.xlen, size[0], 4); self.assertAlmostEqual(bb.ylen, size[1], 4); self.assertAlmostEqual(bb.zlen, height, 4)
            self.assertTrue(all(len(b.meta['ply']['joined']) == 3 for b in walls))             # blacha + dwie sąsiednie ścianki
            self.assertTrue(w.document.get(sheet.id).meta['sheet'].get('dirty'))               # gniazda w blasze
            self.assertEqual(w.document.info['op']['type'], 'sheet_tabwall')
            w.set_mode(None)

    def test_tabwalls_between_bent_flanges_unfold(self):
        w = self.w
        sheet = self._sheet(w)
        sid = sheet.id

        def click(x, y):
            with patch.object(w.view, 'nearest_edge', return_value=(sid, self._edge(w.document.get(sid), x, y))):
                w.view_clicked(5, 5, False, False)
            self.wait()
        w.toggle_mode('flange'); w.fl_length.setValue(30); w.toggle_bending()
        click(50, 0); click(50, 60)
        w.set_mode(None); w.toggle_mode('tabwall'); w.tw_length.setValue(30); w.tw_bend.click()
        click(100, 30); click(0, 30)
        walls = [b for b in w.document.bodies if b.name.startswith('Ścianka blachy')]
        self.assertEqual(len(walls), 2)
        self.assertEqual(_overlaps([b.shape for b in w.document.bodies]), 0)
        w.set_mode(None)
        w.selected = [sid]; w.sheet_command('unfold_sheet'); self.wait()
        self.assertTrue(w.document.get(sid).meta['sheet'].get('flat'))                 # gniazda nie w łuku - blacha się rozkłada
        w.selected = [sid]; w.sheet_command('fold_sheet'); self.wait()
        self.assertFalse(w.document.get(sid).meta['sheet'].get('flat'))

    def test_tabwalls_unfold_fold_drawing_and_library(self):
        """0.4.67: ścianki na noski rozkładają się i składają razem z blachą, idą do biblioteki i na rysunek / DXF."""
        from rccad import library
        w = self.w
        sheet = self._sheet(w)
        sid = sheet.id

        def click(x, y):
            with patch.object(w.view, 'nearest_edge', return_value=(sid, self._edge(w.document.get(sid), x, y))):
                w.view_clicked(5, 5, False, False)
            self.wait()
        w.toggle_mode('flange'); w.fl_length.setValue(30); w.toggle_bending()
        click(50, 0); click(50, 60)
        w.set_mode(None); w.toggle_mode('tabwall'); w.tw_length.setValue(30); w.tw_bend.click()
        click(100, 30); click(0, 30)
        w.set_mode(None)
        walls = [b for b in w.document.bodies if b.name.startswith('Ścianka blachy')]
        self.assertEqual(len({b.group for b in w.document.bodies}), 1)                    # blacha ze ściankami - jeden element
        before = {b.id: np.array(b.shape.Center().toTuple()) for b in w.document.bodies}
        w.selected = [walls[0].id]; w.sheet_command('unfold_sheet'); self.wait()           # klik ścianki - rozkłada całą blachę
        self.assertTrue(w.document.get(sid).meta['sheet'].get('flat'))
        flat = [w.document.get(b.id) for b in walls]
        self.assertTrue(all(abs(b.shape.BoundingBox().zlen - 2) < 1e-6 for b in flat))         # ścianki leżą płasko
        self.assertEqual(_overlaps([b.shape for b in w.document.bodies]), 0)
        # DXF rozwinięcia: kontury blachy i ścianek
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, 'r.dxf')
        with patch('rccad.studio.QFileDialog.getSaveFileName', return_value=(path, '')):
            w.export_flat_pattern(w.document.get(sid)); self.wait()
        import ezdxf
        cut = [e for e in ezdxf.readfile(path).modelspace() if e.dxf.layer == 'CUT']
        ys = [v for e in cut if e.dxftype() == 'LINE' for v in (e.dxf.start.y, e.dxf.end.y)]
        self.assertGreater(max(ys), 120); self.assertLess(min(ys), -20)                       # ścianki obok rozwinięcia
        w.selected = [sid]; w.sheet_command('fold_sheet'); self.wait()
        for b in w.document.bodies:
            self.assertTrue(np.allclose(b.shape.Center().toTuple(), before[b.id], atol=1e-6), b.name)
        # biblioteka: blacha zapisuje się ze ściankami; wstawiona kopia rozkłada się razem z nimi
        lib = library.save_bodies([b for b in w.document.bodies], folder, 'Blacha')
        action = dict(bodies=library.load_bodies('object', lib), name='Blacha', dialog=None)
        w._library_insert(action, np.eye(3), np.array([0.0, 200.0, 0.0])); self.wait()
        copy = next(b for b in w.document.bodies if b.id not in before and (b.meta or {}).get('sheet'))
        cwalls = hist.sheet_tab_walls(w.document.bodies, copy.id)
        self.assertEqual(len(cwalls), 2)
        w.selected = [copy.id]; w.sheet_command('unfold_sheet'); self.wait()
        self.assertTrue(w.document.get(copy.id).meta['sheet'].get('flat'))
        self.assertTrue(all('unfold' in w.document.get(c.id).meta['ply']['tab'] for c in cwalls))

    def test_ply_thickness_from_point_one(self):
        w = self.w
        w.toggle_mode('ply')
        spin = w._ply_widgets[0][1]
        self.assertAlmostEqual(spin.minimum(), .1)
        spin.setValue(.1)
        self.assertAlmostEqual(w.ply_thickness(), .1)
        w.set_mode(None)

    def test_sheet_group_folder_and_uniform_scale_keeps_unfold(self):
        """0.4.68: blacha ze ściankami w jednym folderze na liście Obiekty (ścianki osobno); skala jednakowa
        zachowuje blachę i ścianki - dalej się rozkładają i składają."""
        w = self.w
        sheet = self._sheet(w)
        sid = sheet.id

        def click(x, y):
            with patch.object(w.view, 'nearest_edge', return_value=(sid, self._edge(w.document.get(sid), x, y))):
                w.view_clicked(5, 5, False, False)
            self.wait()
        w.toggle_mode('tabwall'); w.tw_length.setValue(30); w.tw_bend.click()
        click(100, 30); click(0, 30)
        w.set_mode(None)
        self.assertEqual({b.folder for b in w.document.bodies}, {'Blacha'})
        self.app.processEvents()
        self.assertEqual(len(w.objects._members), 3)                              # trzy pozycje w grupie, nie jedna
        w.objects_folder_select([b.id for b in w.document.bodies])
        w.set_mode('scale')
        self.assertEqual(sorted(w.sc_ids), sorted(b.id for b in w.document.bodies))
        w.sc_value.setValue(200); w.apply_scale(); self.wait()
        bb = k.compound([b.shape for b in w.document.bodies]).BoundingBox()
        self.assertAlmostEqual(bb.xlen, 200, 3); self.assertAlmostEqual(bb.zlen, 60, 3)
        self.assertAlmostEqual(w.document.get(sid).meta['sheet']['recipe']['t'], 4)
        self.assertTrue(all(b.meta['ply']['t'] == 4 for b in w.document.bodies if b.id != sid))
        before = {b.id: np.array(b.shape.Center().toTuple()) for b in w.document.bodies}
        w.selected = [sid]; w.sheet_command('unfold_sheet'); self.wait()
        self.assertTrue(w.document.get(sid).meta['sheet'].get('flat'))
        self.assertEqual(_overlaps([b.shape for b in w.document.bodies]), 0)
        w.selected = [sid]; w.sheet_command('fold_sheet'); self.wait()
        for b in w.document.bodies:
            self.assertTrue(np.allclose(b.shape.Center().toTuple(), before[b.id], atol=1e-5), b.name)


class PlywoodSequentialPolygonTests(unittest.TestCase):
    def test_walls_one_by_one_meet_with_fingers_any_polygon(self):
        """0.4.68 (model użytkownika - dziesięciokąt): ścianki dodawane po jednej (Wstaw) schodzą się na skos i łączą
        noskami w każdym narożniku - dowolna liczba kątów, na podstawie i przy boku."""
        import uuid, random
        for n in (5, 7, 10, 12):
            for side in ('on', 'side'):
                t = 1.0
                base = cq.Workplane().polygon(n, 52).extrude(t).val()
                b = Body('Płyta 1', base, meta=pw.ply_meta(t, 'laser')).prepared()
                tops = [i for i, e in enumerate(base.Edges()) if abs(e.Center().z - t) < 1e-6]
                random.Random(n).shuffle(tops)
                bodies = [b]
                for i in tops:
                    bodies = hist.run_recipe(bodies, dict(type='ply_wall', base=b.id, edges=hist.edge_refs(base, [i]), t=t, h=10.0, side=side,
                                                          flip=False, method='laser', out=[uuid.uuid4().hex]))
                panels = pw.panels_of(bodies)
                contacts, skipped = pw.find_contacts(panels)
                self.assertEqual(sum(c['kind'] == 'M' for c in contacts), n, (n, side))
                self.assertFalse(skipped, (n, side))
                for c in contacts:
                    c['joint'] = pw.joint_for('laser', c['kind'])
                failures = []
                out = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method='laser', fit=.1), failures=failures)
                self.assertEqual(failures, [], (n, side))
                self.assertEqual(_overlaps([out.get(p['id'], p['shape']) for p in panels]), 0, (n, side))


class OverlapCornerTests(unittest.TestCase):
    """0.4.69: ścianki nachodzące na siebie w jednej płaszczyźnie (wywinięcia na ściankach w tę samą stronę) -
    narożnik Równolegle / Blacharskie z noskami w płaszczyźnie płyt."""

    def _box_with_lips(self, rule, meth='laser'):
        import uuid
        t = 3.0
        base = cq.Solid.makeBox(100, 60, t)
        b = Body('Płyta 1', base, meta=pw.ply_meta(t, meth)).prepared()
        tops = [i for i, e in enumerate(base.Edges()) if abs(e.Center().z - t) < 1e-6]
        bodies = hist.run_recipe([b], dict(type='ply_wall', base=b.id, edges=hist.edge_refs(base, tops), t=t, h=40.0, side='on', flip=False,
                                           method=meth, corner=rule, out=[uuid.uuid4().hex for _ in tops]))
        walls = [x for x in bodies if x.id != b.id]
        for wb in walls:
            sh = wb.shape
            info = pw.panel_info(sh, t)
            inner = info['hi'] if float(np.array([50, 30, 20.]) @ info['n']) > (info['lo'] + info['hi']) / 2 else info['lo']
            zmax = sh.BoundingBox().zmax
            cand = [i for i, e in enumerate(sh.Edges()) if e.geomType() == 'LINE' and abs(e.startPoint().z - zmax) < 1e-6
                    and abs(e.endPoint().z - zmax) < 1e-6 and abs(float(np.array(e.Center().toTuple()) @ info['n']) - inner) < 1e-6]
            i = max(cand, key=lambda i: sh.Edges()[i].Length())
            bodies = hist.run_recipe(bodies, dict(type='ply_wall', base=wb.id, edges=hist.edge_refs(sh, [i]), t=t, h=15.0, side='on', flip=False,
                                                  method=meth, corner=rule, out=[uuid.uuid4().hex]))
        lips = [x for x in bodies if x.id not in {b.id, *[w.id for w in walls]}]
        return bodies, lips

    def test_lips_meet_with_teeth_both_rules(self):
        for rule in ('sheet', 'parallel'):
            bodies, lips = self._box_with_lips(rule)
            self.assertEqual(len(lips), 4)
            self.assertEqual(_overlaps([x.shape for x in bodies]), 0, rule)
            lip_ids = {x.id for x in lips}
            for x in lips:
                self.assertEqual(len(set(x.meta['ply'].get('joined', [])) & lip_ids), 2, rule)    # obie sąsiednie - noskami
                self.assertTrue(x.shape.isValid() and len(x.shape.Solids()) == 1)
            panels = pw.panels_of(bodies)
            contacts, skipped = pw.find_contacts(panels)
            self.assertFalse(skipped)
            for c in contacts:
                c['joint'] = pw.joint_for('laser', c['kind'])
            failures = []
            out = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, dict(method='laser', fit=.1), failures=failures)
            self.assertEqual(failures, [], rule)
            self.assertEqual(_overlaps([out.get(p['id'], p['shape']) for p in panels]), 0, rule)
        # Blacharskie: styk po przekątnej - wywinięcie sięga do narożnika zewnętrznego
        _, sheet_lips = self._box_with_lips('sheet')
        _, par_lips = self._box_with_lips('parallel')
        short = lambda lips: min(lips, key=lambda x: x.shape.BoundingBox().xlen)
        self.assertLess(short(sheet_lips).shape.BoundingBox().ymin, short(par_lips).shape.BoundingBox().ymin)


class SheetTabBendTests(SheetTabWallTests):
    """0.4.69: na ściance na noski można giąć kołnierz i zawinięcie; ścianki na ściankach w tę samą stronę łączą się
    w narożnikach (Równolegle / Blacharskie) noskami; całość rozkłada się i składa."""

    def test_tabwalls_box_outer_and_inner(self):
        pass

    def test_tabwalls_between_bent_flanges_unfold(self):
        pass

    def test_tabwalls_unfold_fold_drawing_and_library(self):
        pass

    def test_sheet_group_folder_and_uniform_scale_keeps_unfold(self):
        pass

    def test_ply_thickness_from_point_one(self):
        pass

    def _click(self, bid, p):
        w = self.w
        sh = w.document.get(bid).shape
        cand = [i for i, e in enumerate(sh.Edges()) if e.geomType() == 'LINE']
        i = min(cand, key=lambda i: np.linalg.norm(np.array(sh.Edges()[i].positionAt(.5).toTuple()) - p))
        with patch.object(w.view, 'nearest_edge', return_value=(bid, i)):
            w.view_clicked(5, 5, False, False)
        self.wait()

    def test_flange_and_hem_on_tabwall_unfold_fold(self):
        w = self.w
        sheet = self._sheet(w)
        w.toggle_mode('tabwall'); w.tw_length.setValue(30); w.tw_bend.click()
        self._click(sheet.id, (100, 30, 2))
        w.set_mode(None)
        wall = next(b for b in w.document.bodies if b.name.startswith('Ścianka blachy'))
        self.assertIn('sheet', wall.meta)
        w.toggle_mode('flange'); w.fl_length.setValue(15); w.toggle_bending()
        self._click(wall.id, (100, 30, 30))
        self.assertEqual(w.document.info['label'], 'Kołnierz')
        w.set_mode(None)
        w.toggle_mode('hem'); w.toggle_bending()
        self._click(wall.id, (115, 30, 30))
        self.assertEqual(w.document.info['label'], 'Zawinięcie')
        w.set_mode(None)
        wall = w.document.get(wall.id)
        self.assertEqual(len(wall.meta['sheet']['recipe']['flanges']), 2)
        self.assertIn('ply', wall.meta)                                                          # dalej ścianka na noski
        before = {b.id: (np.array(b.shape.Center().toTuple()), b.shape.Volume()) for b in w.document.bodies}
        w.selected = [sheet.id]; w.sheet_command('unfold_sheet'); self.wait()
        self.assertTrue(w.document.get(wall.id).meta['sheet'].get('flat'))                      # ścianka też rozłożona
        self.assertLess(w.document.get(wall.id).shape.BoundingBox().zlen, 2.01)
        self.assertEqual(_overlaps([b.shape for b in w.document.bodies]), 0)
        w.selected = [sheet.id]; w.sheet_command('fold_sheet'); self.wait()
        for b in w.document.bodies:
            c, v = before[b.id]
            self.assertTrue(np.allclose(b.shape.Center().toTuple(), c, atol=1e-5), b.name)
            self.assertAlmostEqual(b.shape.Volume(), v, 4)

    def test_sheet_flange_hem_and_tabwall_steps_reopen_with_their_edges(self):
        """0.5.1: dwuklik w krok blachy otwiera to samo narzędzie z krawędzią i wartościami z kroku; Zatwierdź zastępuje krok."""
        w = self.w
        sheet = self._sheet(w)
        w.toggle_mode('tabwall'); w.tw_length.setValue(30); w.tw_bend.click()
        self._click(sheet.id, (100, 30, 2))
        w.set_mode(None)
        wall = next(b for b in w.document.bodies if b.name.startswith('Ścianka blachy'))
        w.toggle_mode('flange'); w.fl_length.setValue(15); w.toggle_bending()
        self._click(wall.id, (100, 30, 30))
        w.set_mode(None)
        w.toggle_mode('hem'); w.toggle_bending()
        self._click(wall.id, (115, 30, 30))
        w.set_mode(None)
        doc = w.document
        infos = doc.infos()[0]; count = len(infos)
        steps = {i['label']: n for n, i in enumerate(infos)}
        # kołnierz: ta sama krawędź, długość z kroku; nowa długość zastępuje krok
        w.history_edit(steps['Kołnierz']); self.app.processEvents()
        self.assertEqual(w.mode, 'flange'); self.assertIsNotNone(w.fl_pick); self.assertAlmostEqual(w.fl_length.value(), 15)
        w.fl_length.setValue(20); w.apply_flange(); self.wait(); self.wait()
        infos = doc.infos()[0]
        self.assertEqual(len(infos), count); self.assertFalse(any(i.get('stale') for i in infos))
        flanges = doc.get(wall.id).meta['sheet']['recipe']['flanges']
        self.assertEqual(len(flanges), 2); self.assertAlmostEqual(float(flanges[0]['length']), 20)
        # zawinięcie: otwiera się Zawinięcie z wartościami z kroku
        w.history_edit(steps['Zawinięcie']); self.app.processEvents()
        self.assertEqual(w.mode, 'hem'); self.assertIsNotNone(w.fl_pick)
        w.set_mode(None); self.app.processEvents(); self.wait()
        self.assertEqual(doc.infos()[1], count - 1)
        # ścianka na noski: krawędź z kroku, wysokość z kroku
        w.history_edit(steps['Kołnierz na noski']); self.app.processEvents()
        self.assertEqual(w.mode, 'tabwall'); self.assertIsNotNone(w.tw_pick); self.assertAlmostEqual(w.tw_length.value(), 30)
        w.tw_length.setValue(35); w._tw_save(); self.wait(); self.wait()
        infos = doc.infos()[0]
        self.assertEqual(len(infos), count); self.assertAlmostEqual(infos[steps['Kołnierz na noski']]['op']['length'], 35)
        # zamiana na blachę: ta sama ściana
        w.history_edit(steps.get('Konwersja na blachę', 1) if 'Konwersja na blachę' in steps else 1); self.app.processEvents()
        if w.mode == 'sheet':
            self.assertIsNotNone(w.sheet_pick); self.assertEqual(w.sheet_pick['id'], sheet.id)
        w.set_mode(None); self.app.processEvents(); self.wait()

    def test_side_flange_on_tabwall_keeps_fingers_in_place(self):
        # kołnierz przy bocznej krawędzi ścianki (od strony początku jej płyty) przesuwał noski o promień + grubość
        w = self.w
        sheet = self._sheet(w)
        w.toggle_mode('tabwall'); w.tw_length.setValue(30); w.tw_bend.click()
        self._click(sheet.id, (100, 30, 2))
        w.set_mode(None)
        wall = next(b for b in w.document.bodies if b.name.startswith('Ścianka blachy'))
        w.toggle_mode('flange'); w.fl_length.setValue(12); w.toggle_bending()
        self._click(wall.id, (100, 0, 16))
        self.assertEqual(w.document.info['label'], 'Kołnierz')
        w.set_mode(None)
        self.assertEqual(_overlaps([b.shape for b in w.document.bodies]), 0)
        self.assertLess(w.document.get(wall.id).shape.BoundingBox().ymax, 60 + 1e-5)
        before = {b.id: np.array(b.shape.Center().toTuple()) for b in w.document.bodies}
        w.selected = [sheet.id]; w.sheet_command('unfold_sheet'); self.wait()
        self.assertTrue(w.document.get(wall.id).meta['sheet'].get('flat'))
        w.selected = [sheet.id]; w.sheet_command('fold_sheet'); self.wait()
        for b in w.document.bodies:
            self.assertTrue(np.allclose(b.shape.Center().toTuple(), before[b.id], atol=1e-5), b.name)

    def test_tabwall_lips_corner_rules(self):
        for rule in ('sheet', 'parallel'):
            w = self.w
            w.document = type(w.document)()
            sheet = self._sheet(w)
            w.toggle_mode('tabwall'); w.tw_length.setValue(30); w.tw_corner.setCurrentIndex(w.tw_corner.findData(rule)); w.tw_bend.click()
            for p in ((50, 0, 2), (100, 30, 2), (50, 60, 2), (0, 30, 2)):
                self._click(sheet.id, p)
            walls = [x for x in w.document.bodies if x.name.startswith('Ścianka')]
            w.tw_length.setValue(12)
            for wb in walls:
                sh = w.document.get(wb.id).shape
                info = pw.panel_info(sh, 2)
                zmax = sh.BoundingBox().zmax
                inner = info['hi'] if float(np.array([50, 30, 15]) @ info['n']) > (info['lo'] + info['hi']) / 2 else info['lo']
                cand = [i for i, e in enumerate(sh.Edges()) if e.geomType() == 'LINE' and abs(e.startPoint().z - zmax) < 1e-6
                        and abs(e.endPoint().z - zmax) < 1e-6 and abs(float(np.array(e.Center().toTuple()) @ info['n']) - inner) < 1e-6]
                i = max(cand, key=lambda i: sh.Edges()[i].Length())
                with patch.object(w.view, 'nearest_edge', return_value=(wb.id, i)):
                    w.view_clicked(5, 5, False, False)
                self.wait()
            w.set_mode(None)
            lips = [x for x in w.document.bodies if x.name.startswith('Ścianka') and x.id not in {v.id for v in walls}]
            self.assertEqual(len(lips), 4, rule)
            self.assertEqual(_overlaps([x.shape for x in w.document.bodies]), 0, rule)
            ids = {x.id for x in lips}
            self.assertTrue(all(len(set(x.meta['ply']['joined']) & ids) == 2 for x in lips), rule)
            w.selected = [sheet.id]; w.sheet_command('unfold_sheet'); self.wait()
            self.assertTrue(w.document.get(sheet.id).meta['sheet'].get('flat'), rule)
            self.assertEqual(_overlaps([x.shape for x in w.document.bodies]), 0, rule)


class PlyCutPickTests(PlywoodWindowTests):
    def test_tab_tools_and_full_flow(self):
        pass

    def test_cut_selected_hover_color_click_and_right_click(self):
        """0.4.69: Do cięcia - płyta pod kursorem podświetla się, kliknięcie dodaje (bez Shift), wybrane mają inny kolor,
        prawy przycisk odznacza."""
        from rccad.studio import TINT_TOOL
        w = self.w
        a = Body('Płyta A', cq.Solid.makeBox(50, 40, 4), meta=pw.ply_meta(4, 'laser')).prepared()
        b = Body('Płyta B', cq.Solid.makeBox(50, 40, 4).translate(cq.Vector(80, 0, 0)), meta=pw.ply_meta(4, 'laser')).prepared()
        w.document.commit([a, b]); w.refresh()
        w.selected = []
        w.toggle_mode('ply_cut')
        with patch.object(w.view, 'pick_face', return_value=(a.id, [0, 0, 1], [10, 10, 4])):
            w.ply_hover(5, 5)
        self.assertEqual(w._hover_key, ('shellsolid', a.id))                              # podświetlenie przed kliknięciem
        for bid in (a.id, b.id):
            with patch.object(w.view, 'pick_body', return_value=bid):
                w.view_clicked(5, 5, False, False)
        self.assertEqual(w.pc_scope.currentData(), 'sel')
        self.assertEqual(sorted(w.selected), sorted([a.id, b.id]))                        # bez Shift - obie
        self.assertEqual(w.view.tints, {a.id: TINT_TOOL, b.id: TINT_TOOL})
        with patch.object(w.view, 'pick_body', return_value=a.id):
            w.context_menu(5, 5)                                                          # prawy przycisk odznacza
        self.assertEqual(w.selected, [b.id])
        self.assertEqual(w.view.tints, {b.id: TINT_TOOL})
        self.assertEqual([x.id for x in w._pc_bodies()], [b.id])
        w.set_mode(None)
        self.assertEqual(w.view.tints, {})


class SheetTabVariantTests(SheetTabBendTests):
    """0.4.72: blacha gięta ze ściankami na noski w różnej kolejności - gięcie po ściankach (ścianki liczą się od nowa),
    noski do ramion kołnierzy giętych, zawinięcia na kołnierzach i na ściankach, wywinięcia na ściankach."""

    def test_flange_and_hem_on_tabwall_unfold_fold(self):
        pass

    def test_tabwall_lips_corner_rules(self):
        pass

    def _mode(self, mode, length=None):
        w = self.w
        w.set_mode(None)
        w.toggle_mode(mode)
        if mode == 'tabwall':
            if length:
                w.tw_length.setValue(length)
            if not w.tw_armed:
                w.tw_bend.click()
        else:
            if length and mode == 'flange':
                w.fl_length.setValue(length)
            if not w.fl_armed:
                w.toggle_bending()

    def _check(self, sid):
        w = self.w
        from rccad import sheetedit as she
        self.assertEqual(_overlaps([b.shape for b in w.document.bodies]), 0)
        before = {b.id: np.array(b.shape.Center().toTuple()) for b in w.document.bodies}
        w.selected = [sid]; w.sheet_command('unfold_sheet'); self.wait()
        self.assertTrue(w.document.get(sid).meta['sheet'].get('flat'))
        self.assertEqual(_overlaps([b.shape for b in w.document.bodies]), 0)
        w.selected = [sid]; w.sheet_command('fold_sheet'); self.wait()
        for b in w.document.bodies:
            self.assertTrue(np.allclose(b.shape.Center().toTuple(), before[b.id], atol=1e-5), b.name)

    def test_bend_after_tabwalls_regenerates_them_with_fingers_to_flange(self):
        from rccad import sheetedit as she
        w = self.w
        sid = self._sheet(w).id
        self._mode('tabwall', 30)
        self._click(sid, (100, 30, 2)); self._click(sid, (0, 30, 2))
        self._mode('flange', 30)
        self._click(sid, (50, 0, 2))
        self.assertEqual(w.document.info['label'], 'Kołnierz')                           # wcześniej: „Nie można dokładnie przenieść…”
        w.set_mode(None)
        model = she.layout(w.document.get(sid).meta['sheet']['recipe'])
        walls = [b for b in w.document.bodies if b.name.startswith('Ścianka blachy')]
        self.assertEqual([b.name for b in walls], ['Ścianka blachy 1', 'Ścianka blachy 2'])
        for wall in walls:
            self.assertGreater(wall.shape.intersect(model.panels[1].folded).Volume(), 1)   # noski w ramieniu nowego kołnierza
        self._check(sid)
        # zawinięcie na nowym kołnierzu i drugi kołnierz - ścianki dalej dopasowują się same
        self._mode('hem'); self._click(sid, (50, -1, 32))
        self._mode('flange', 30); self._click(sid, (50, 60, 2))
        self.assertEqual(w.document.info['label'], 'Kołnierz')
        w.set_mode(None)
        self._check(sid)

    def test_hem_on_tabwalls_and_lips_then_bend(self):
        w = self.w
        sid = self._sheet(w).id
        self._mode('flange', 30); self._click(sid, (50, 0, 2)); self._click(sid, (50, 60, 2))
        self._mode('tabwall', 30); self._click(sid, (100, 30, 2)); self._click(sid, (0, 30, 2))
        walls = [b for b in w.document.bodies if b.name.startswith('Ścianka blachy')]
        bb = walls[0].shape.BoundingBox()
        self._mode('hem'); self._click(walls[0].id, ((bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, bb.zmax))
        self.assertEqual(w.document.info['label'], 'Zawinięcie')
        w.set_mode(None)
        self._check(sid)
        # wywinięcie na drugiej ściance, potem gięcie blachy nie nachodzi na nic
        w.document = type(w.document)()
        sid = self._sheet(w).id
        self._mode('tabwall', 30); self._click(sid, (100, 30, 2)); self._click(sid, (0, 30, 2))
        for wb in [b for b in w.document.bodies if b.name.startswith('Ścianka blachy')]:
            bb = wb.shape.BoundingBox()
            self._mode('tabwall', 10); self._click(wb.id, ((bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, bb.zmax))
        self._mode('flange', 30); self._click(sid, (50, 0, 2))
        self.assertEqual(w.document.info['label'], 'Kołnierz')
        w.set_mode(None)
        self.assertEqual(len([b for b in w.document.bodies if b.name.startswith('Ścianka blachy')]), 4)
        self._check(sid)
