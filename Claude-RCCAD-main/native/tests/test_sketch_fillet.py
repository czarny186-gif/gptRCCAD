"""Zaokrąglenie / faza narożników szkicu (0.5.32): geometria w kernel.sketch_fillet i krok historii 'sketch_fillet'."""
import math
import unittest

import cadquery as cq
import numpy as np

from rccad import history as hist
from rccad import kernel as k
from rccad.document import Body


def area(wire):
    return cq.Face.makeFromWires(wire).Area()


class SketchFilletTests(unittest.TestCase):
    def rect(self, w=20, h=10, plane='XY'):
        return k.polyline(plane, [(0, 0), (w, 0), (w, h), (0, h)], closed=True)

    def test_corners_of_rectangle_slot_and_polyline(self):
        self.assertEqual(len(k.sketch_corners(self.rect())), 4)
        slot = k.sketch_shape('slot', 'XY', [(0, 0), (20, 0), (20, 3)])
        self.assertEqual(k.sketch_corners(slot), [])                    # odcinki styczne do łuków - brak narożników
        open_line = k.polyline('XY', [(0, 0), (10, 0), (10, 10), (20, 10)])
        self.assertEqual(len(k.sketch_corners(open_line)), 2)          # końce otwartej łamanej to nie narożniki

    def test_fillet_and_chamfer_areas(self):
        wire = self.rect()
        all4 = k.sketch_corners(wire)
        r = 2.0
        filleted = k.sketch_fillet(wire, 'XY', all4, r)
        self.assertTrue(filleted.IsClosed())
        self.assertAlmostEqual(area(filleted), 200 - 4 * (r * r - math.pi * r * r / 4), 6)
        chamfered = k.sketch_fillet(wire, 'XY', all4, 1.5, 'chamfer')
        self.assertAlmostEqual(area(chamfered), 200 - 4 * 1.5 * 1.5 / 2, 6)
        one = k.sketch_fillet(wire, 'XY', [all4[0]], r)
        self.assertEqual(len(one.Edges()), 5)

    def test_hexagon_and_other_planes(self):
        hexagon = k.polyline('XZ', [(10 * math.cos(a), 10 * math.sin(a)) for a in np.radians(np.arange(0, 360, 60))], closed=True)
        corners = k.sketch_corners(hexagon)
        self.assertEqual(len(corners), 6)
        out = k.sketch_fillet(hexagon, 'XZ', corners, 1.0)
        # wypukły wielokąt: pole minus n * (r² · tan(π/n·…) - wycinek) - kąt zewnętrzny 60°
        turn = math.pi / 3
        loss = 6 * (math.tan(turn / 2) - turn / 2)
        self.assertAlmostEqual(area(out), 1.5 * math.sqrt(3) * 100 - loss, 5)
        bb = out.BoundingBox()
        self.assertAlmostEqual(bb.ylen, 0, 9)                           # dalej w płaszczyźnie XZ

    def test_sketch_on_tilted_face_frame(self):
        fr = k.face_frame((0, 0, 5), (0, 1, 1))
        wire = k.sketch('rectangle', fr, 20, 10)
        corners = k.sketch_corners(wire)
        self.assertEqual(len(corners), 4)
        out = k.sketch_fillet(wire, fr, corners, 2)
        self.assertAlmostEqual(area(out), 200 - 4 * (4 - math.pi), 6)
        n = np.array([0, 1, 1]) / math.sqrt(2)
        pts = np.array([e.positionAt(t).toTuple() for e in out.Edges() for t in (0, .5, 1)])
        self.assertLess(float(np.max(np.abs((pts - (0, 0, 5)) @ n))), 1e-7)    # dalej w płaszczyźnie ściany

    def test_open_polyline_and_errors(self):
        line = k.polyline('XY', [(0, 0), (10, 0), (10, 10)])
        out = k.sketch_fillet(line, 'XY', k.sketch_corners(line), 3)
        self.assertFalse(out.IsClosed())
        self.assertAlmostEqual(sum(e.Length() for e in out.Edges()), 20 - 6 + math.pi * 3 / 2, 6)
        with self.assertRaises(k.CadError):
            k.sketch_fillet(line, 'XY', k.sketch_corners(line), 12)     # promień większy niż krawędź
        with self.assertRaises(k.CadError):
            k.sketch_fillet(line, 'XY', [np.array([5.0, 5.0, 0.0])], 1)  # punkt, który nie jest narożnikiem
        with self.assertRaises(k.CadError):
            k.sketch_fillet(line, 'XY', k.sketch_corners(line), 0)

    def test_corner_handle_points_into_the_angle(self):
        corner, d = k.sketch_corner_handle(self.rect(), (20, 10, 0))
        np.testing.assert_allclose(corner, (20, 10, 0), atol=1e-9)
        np.testing.assert_allclose(d, np.array([-1, -1, 0]) / math.sqrt(2), atol=1e-9)

    def test_history_step_and_replay_after_sketch_change(self):
        body = Body('Prostokąt', self.rect(), 'sketch', 'XY').prepared()
        corners = k.sketch_corners(body.shape)
        recipe = dict(type='sketch_fillet', kind='fillet', size=2.0,
                      items=[dict(id=body.id, corners=[list(map(float, corners[2]))], index=[2])])
        self.assertEqual(set(hist.reads(recipe, [body])), {body.id})
        out = hist.RUNNERS['sketch_fillet']([body], recipe)
        self.assertEqual(out[0].id, body.id)
        self.assertEqual(len(out[0].shape.Edges()), 5)
        # szkic zmieniony wcześniej w historii (30 × 10): narożnik szukany po kolejności
        wider = body.changed(self.rect(30, 10))
        out = hist.RUNNERS['sketch_fillet']([wider], recipe)
        self.assertAlmostEqual(area(out[0].shape), 300 - (4 - math.pi), 6)
        solid = Body('B', k.box(5, 5, 5)).prepared()
        with self.assertRaises(k.CadError):
            hist.RUNNERS['sketch_fillet']([solid], dict(recipe, items=[dict(id=solid.id, corners=[[0, 0, 0]])]))


if __name__ == '__main__':
    unittest.main()
