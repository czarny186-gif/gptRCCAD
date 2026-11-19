"""Silnik kół zębatych (rccad.gears): wymiary pochodne i walidacja - bez Qt i bez Open CASCADE."""
import math
import os
import subprocess
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from rccad import gears
from rccad.gears import GearParams, derived, validate


def levels(checks, field=None):
    return [(c.level, c.field) for c in checks if field is None or c.field == field]


class GearDimensionTests(unittest.TestCase):
    def test_spur_external_standard_dimensions(self):
        g = derived(GearParams(module=2, teeth=20, pressure=20, backlash=0))
        self.assertAlmostEqual(g['d'], 40)
        self.assertAlmostEqual(g['da'], 44)
        self.assertAlmostEqual(g['df'], 35)
        self.assertAlmostEqual(g['db'], 40 * math.cos(math.radians(20)))
        self.assertAlmostEqual(g['height'], 4.5)
        self.assertAlmostEqual(g['s'], math.pi)                       # grubość zęba = połowa podziałki
        self.assertAlmostEqual(g['pitch'], 2 * math.pi)

    def test_profile_shift_and_backlash(self):
        g = derived(GearParams(module=2, teeth=20, shift=.5, backlash=.2))
        self.assertAlmostEqual(g['da'], 46)
        self.assertAlmostEqual(g['df'], 37)
        self.assertAlmostEqual(g['s'], 2 * (math.pi / 2 + 2 * .5 * math.tan(math.radians(20))) - .1)

    def test_helical_uses_transverse_module(self):
        g = derived(GearParams(kind='helical_ext', module=2, teeth=20, helix=30))
        mt = 2 / math.cos(math.radians(30))
        self.assertAlmostEqual(g['mt'], mt)
        self.assertAlmostEqual(g['d'], 20 * mt)
        self.assertAlmostEqual(g['da'], 20 * mt + 4)
        self.assertAlmostEqual(g['alpha_t'], math.degrees(math.atan(math.tan(math.radians(20)) / math.cos(math.radians(30)))))
        # zęby proste ignorują zapamiętany kąt pochylenia
        self.assertAlmostEqual(derived(GearParams(kind='spur_ext', module=2, teeth=20, helix=30))['d'], 40)

    def test_internal_gear_tips_inside_roots_outside(self):
        g = derived(GearParams(kind='spur_int', module=2, teeth=60))
        self.assertAlmostEqual(g['d'], 120)
        self.assertAlmostEqual(g['da'], 116)
        self.assertAlmostEqual(g['df'], 125)
        self.assertAlmostEqual(g['rim'], 125 + 10)                    # wieniec dobrany sam: 2,5·m pod stopami
        self.assertAlmostEqual(derived(GearParams(kind='spur_int', module=2, teeth=60, rim_diameter=150))['rim'], 150)


class GearValidationTests(unittest.TestCase):
    def test_defaults_are_valid_for_every_kind(self):
        for kind in gears.KINDS:
            self.assertEqual(validate(GearParams(kind=kind, teeth=60 if kind.endswith('_int') else 20)), [], kind)

    def test_ranges_are_errors(self):
        self.assertIn(('error', 'module'), levels(validate(GearParams(module=0))))
        self.assertIn(('error', 'teeth'), levels(validate(GearParams(teeth=3))))
        self.assertIn(('error', 'pressure'), levels(validate(GearParams(pressure=40))))
        self.assertIn(('error', 'width'), levels(validate(GearParams(width=0))))
        self.assertIn(('error', 'shift'), levels(validate(GearParams(shift=2))))
        self.assertIn(('error', 'backlash'), levels(validate(GearParams(backlash=-.1))))
        self.assertIn(('error', 'backlash'), levels(validate(GearParams(module=1, backlash=.6))))
        self.assertIn(('error', 'teeth'), levels(validate(GearParams(teeth=20.5))))
        self.assertIn(('error', 'kind'), levels(validate(GearParams(kind='bevel'))))

    def test_helix_angle_checked_only_for_helical(self):
        self.assertIn(('error', 'helix'), levels(validate(GearParams(kind='helical_ext', helix=0))))
        self.assertIn(('error', 'helix'), levels(validate(GearParams(kind='helical_ext', helix=50))))
        self.assertEqual(validate(GearParams(kind='spur_ext', helix=0)), [])
        self.assertIn(('error', 'hand'), levels(validate(GearParams(kind='helical_ext', hand='up'))))

    def test_undercut_is_a_warning_and_profile_shift_removes_it(self):
        self.assertEqual(levels(validate(GearParams(teeth=12))), [('warning', 'teeth')])
        self.assertEqual(validate(GearParams(teeth=12, shift=.4)), [])
        self.assertEqual(validate(GearParams(teeth=15, backlash=.1)), [])                    # granica praktyczna (DIN 3960)

    def test_pointed_tooth(self):
        self.assertIn(('error', 'shift'), levels(validate(GearParams(teeth=6, shift=1.5))))
        self.assertIn(('error', 'shift'), levels(validate(GearParams(teeth=10, shift=.9))))
        self.assertIn(('warning', 'shift'), levels(validate(GearParams(teeth=10, shift=.6))))

    def test_bore_and_hub(self):
        self.assertIn(('error', 'bore'), levels(validate(GearParams(module=2, teeth=20, bore=34))))
        self.assertIn(('warning', 'bore'), levels(validate(GearParams(module=2, teeth=20, bore=28))))
        self.assertEqual(validate(GearParams(module=2, teeth=20, bore=10)), [])
        hub = dict(module=2, teeth=20, bore=10, hub=True)
        self.assertEqual(validate(GearParams(hub_diameter=20, hub_length=8, **hub)), [])
        self.assertIn(('error', 'hub_diameter'), levels(validate(GearParams(hub_diameter=10, hub_length=8, **hub))))
        self.assertIn(('error', 'hub_length'), levels(validate(GearParams(hub_diameter=20, hub_length=0, **hub))))
        self.assertIn(('warning', 'hub_diameter'), levels(validate(GearParams(hub_diameter=38, hub_length=8, **hub))))
        self.assertEqual(validate(GearParams(module=2, teeth=20, hub=False, hub_diameter=0)), [])   # piasta wyłączona - pola nieważne

    def test_internal_gear_limits(self):
        self.assertIn(('error', 'teeth'), levels(validate(GearParams(kind='spur_int', teeth=12))))   # głowy w okręgu zasadniczym
        self.assertIn(('error', 'teeth'), levels(validate(GearParams(kind='spur_int', teeth=33))))   # bez korekcji: co najmniej 34
        self.assertEqual(validate(GearParams(kind='spur_int', teeth=34)), [])
        self.assertEqual(validate(GearParams(kind='spur_int', teeth=20, shift=.8)), [])               # korekcja podnosi głowy
        self.assertIn(('error', 'rim_diameter'), levels(validate(GearParams(kind='spur_int', module=2, teeth=60, rim_diameter=126))))
        self.assertIn(('warning', 'rim_diameter'), levels(validate(GearParams(kind='spur_int', module=2, teeth=60, rim_diameter=130))))
        self.assertEqual(validate(GearParams(kind='spur_int', module=2, teeth=60, rim_diameter=140, bore=500)), [])  # otwór nie dotyczy wieńca

    def test_dict_round_trip_ignores_unknown_keys(self):
        p = GearParams(kind='helical_int', module=1.5, teeth=48, helix=20, hand='left', rim_diameter=90)
        data = p.to_dict()
        data['future_option'] = 1
        self.assertEqual(GearParams.from_dict(data), p)
        self.assertEqual(GearParams.from_dict({'teeth': 19.6}).teeth, 20)

    def test_engine_does_not_import_qt_or_occ(self):
        code = ('import sys; sys.path.insert(0, "."); import rccad.gears; '
                'print(any(m.startswith(("PySide6", "OCP", "cadquery")) for m in sys.modules))')
        out = subprocess.run([sys.executable, '-c', code], cwd=os.path.join(os.path.dirname(__file__), '..'),
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.stdout.strip(), 'False', out.stderr)


class GearNumericTests(unittest.TestCase):
    """Wielkości liczbowe etapu 2: podziałki, grubości, moduł normalny i czołowy, dokładna granica podcięcia."""

    def test_pitches_and_thicknesses(self):
        g = derived(GearParams(kind='helical_ext', module=3, teeth=25, helix=18, shift=.3, backlash=.12))
        beta, an = math.radians(18), math.radians(20)
        at = math.atan(math.tan(an) / math.cos(beta))
        self.assertAlmostEqual(g['mn'], 3)
        self.assertAlmostEqual(g['mt'], 3 / math.cos(beta))
        self.assertAlmostEqual(g['pn'], 3 * math.pi)
        self.assertAlmostEqual(g['pt'], 3 * math.pi / math.cos(beta))
        self.assertAlmostEqual(g['pb'], g['pt'] * math.cos(at))
        self.assertAlmostEqual(g['pb'], math.pi * g['db'] / 25)                    # podziałka zasadnicza = obwód zasadniczy / z
        self.assertAlmostEqual(g['s_n'], 3 * (math.pi / 2 + 2 * .3 * math.tan(an)) - .06)
        self.assertAlmostEqual(g['s'], g['s_n'] / math.cos(beta))
        self.assertAlmostEqual(g['s'] + g['e'], g['pt'])
        self.assertAlmostEqual(g['s_b'], g['db'] * (g['s'] / g['d'] + gears.inv(at)))

    def test_exact_undercut_limit_matches_rack_geometry(self):
        # zębatka ISO 53 (stopa 1,25·m, zaokrąglenie 0,38·m): bez korekcji podcięcie kończy się między 17 a 18 zębami
        self.assertTrue(derived(GearParams(teeth=17, backlash=0))['undercut'])
        self.assertFalse(derived(GearParams(teeth=18, backlash=0))['undercut'])
        g = derived(GearParams(teeth=10))
        self.assertTrue(g['undercut'])
        self.assertFalse(derived(GearParams(teeth=10, shift=g['x_min'] + 1e-6))['undercut'])
        self.assertTrue(derived(GearParams(teeth=10, shift=g['x_min'] - 1e-3))['undercut'])
        self.assertFalse(derived(GearParams(kind='spur_int', teeth=60))['undercut'])        # koło wewnętrzne: nie dotyczy

    def test_rack_tip_radius_shrinks_when_it_does_not_fit(self):
        self.assertAlmostEqual(derived(GearParams(module=2))['rho'], .76)
        self.assertLess(gears.rack_rho(GearParams(module=2, shift=-.9, teeth=60)), .76 + 1e-12)


def _simulated_tooth_area(p, steps=1500):
    """Niezależna kontrola: koło głów nacinane wielobokiem zębatki w wielu położeniach (manifold3d), pole jednego zęba."""
    import manifold3d as mf
    g = derived(p)
    m, alpha, r, ra, s_t, rho, z, pt = p.module, math.radians(g['alpha_t']), g['d'] / 2, g['da'] / 2, g['s'], g['rho'], p.teeth, g['pt']
    v_c = (p.shift - 1.25) * m + rho
    u_c = s_t / 2 - v_c * math.tan(alpha) + rho / math.cos(alpha)
    top = ra - r + 3 * m
    half = [(s_t / 2 - top * math.tan(alpha), top)] + [(u_c + rho * math.cos(a), v_c + rho * math.sin(a))
                                                       for a in np.linspace(math.pi + alpha, 1.5 * math.pi, 60)]
    tooth = half + [(pt - u, v) for u, v in reversed(half)]
    rack = [[(u + k * pt, v) for u, v in tooth] for k in range(-3, 4)]
    cut = mf.CrossSection.circle(ra, 2000)
    for phi in np.linspace(-.9, .9, steps):
        c, s = math.cos(phi), math.sin(phi)
        polys = [[((-(u - r * phi) * s + (r + v) * c), -((u - r * phi) * c + (r + v) * s)) for u, v in t] for t in rack]
        cut = cut - mf.CrossSection(polys, mf.FillRule.NonZero)
    hp = math.pi / z
    sector = mf.CrossSection([[(0, 0), (2 * ra * math.cos(hp), -2 * ra * math.sin(hp)), (2 * ra, 0), (2 * ra * math.cos(hp), 2 * ra * math.sin(hp))]])
    return (cut ^ sector).area()


class GearProfileTests(unittest.TestCase):
    """Zarys zęba (numpy): ewolwenta, trochoida stopy, połączenia, podcięcie, błędy."""

    def theta(self, xy):
        return math.atan2(xy[1], xy[0])

    def test_flank_is_the_exact_involute(self):
        p = GearParams(module=2, teeth=20)
        pr, g = gears.profile(p), derived(p)
        rb, at = g['db'] / 2, math.radians(g['alpha_t'])
        for x, y in pr.flank:
            R = math.hypot(x, y)
            self.assertAlmostEqual(math.atan2(y, x), g['s'] / g['d'] + gears.inv(at) - gears.inv(math.acos(rb / R)), places=12)
        self.assertAlmostEqual(math.hypot(*pr.flank[-1]), g['da'] / 2, places=12)
        self.assertAlmostEqual(pr.tip_angle * g['da'], g['s_a'], places=9)          # grubość wierzchołka (łuk)

    def test_root_fillet_is_tangent_to_involute_without_undercut(self):
        pr = gears.profile(GearParams(module=2, teeth=30))
        self.assertFalse(pr.undercut)
        self.assertGreater(pr.r_form, pr.rb)
        np.testing.assert_allclose(pr.fillet[-1], pr.flank[0], atol=1e-12)          # wspólny punkt
        a = pr.fillet[-1] - pr.fillet[-2]
        b = pr.flank[1] - pr.flank[0]
        cos = np.dot(a, b) / np.linalg.norm(a) / np.linalg.norm(b)
        self.assertGreater(cos, math.cos(math.radians(1.5)))                         # styczne (różnica kierunku z próbkowania)
        self.assertAlmostEqual(math.hypot(*pr.fillet[0]), pr.rf, places=9)          # trochoida zaczyna się na okręgu stóp
        self.assertLess(pr.root_angle, math.pi / 30)

    def test_undercut_is_detected_and_cut_into_the_involute(self):
        pr = gears.profile(GearParams(module=2, teeth=8))
        self.assertTrue(pr.undercut)
        self.assertGreater(pr.r_form, pr.rb + .05)                                   # ewolwenta zaczyna się wyżej - podcięta
        with self.assertRaises(gears.GearError):                                       # korekcja usuwa podcięcie, ale zaostrza ząb
            gears.profile(GearParams(module=2, teeth=8, shift=.6))
        x_min = derived(GearParams(module=2, teeth=10))['x_min']
        self.assertFalse(gears.profile(GearParams(module=2, teeth=10, shift=x_min + .01)).undercut)
        self.assertTrue(gears.profile(GearParams(module=2, teeth=10, shift=x_min - .05)).undercut)
        for z in range(10, 26):
            self.assertEqual(gears.profile(GearParams(teeth=z, backlash=0)).undercut, derived(GearParams(teeth=z, backlash=0))['undercut'], z)

    def test_generated_profile_matches_independent_rack_cutting_simulation(self):
        for kw in (dict(teeth=20), dict(teeth=8), dict(kind='helical_ext', teeth=12, helix=20)):
            p = GearParams(**kw)
            ours = gears.polygon_area(gears.outline_points(p, 600)) / p.teeth
            sim = _simulated_tooth_area(p)
            self.assertLess(abs(sim - ours) / ours, 1e-4, kw)

    def test_internal_tooth(self):
        p = GearParams(kind='spur_int', module=2, teeth=60)
        pr, g = gears.profile(p), derived(p)
        r = g['d'] / 2
        R = np.hypot(*gears.outline_points(p).T)
        self.assertAlmostEqual(R.min(), g['da'] / 2, places=9)
        self.assertAlmostEqual(R.max(), g['df'] / 2, places=9)
        # grubość zęba wewnętrznego na średnicy podziałowej
        at = math.radians(g['alpha_t'])
        half = math.pi / 60 - (g['e'] / (2 * r) + gears.inv(at) - gears.inv(math.acos(g['db'] / g['d'])))
        self.assertAlmostEqual(2 * half * r, g['s'], places=9)
        cx, cy = pr.fillet_center                                                     # łuk przejścia styczny do okręgu stóp i do boku
        self.assertAlmostEqual(math.hypot(cx, cy) + pr.rho, pr.rf, places=9)
        self.assertAlmostEqual(np.linalg.norm(pr.fillet[2] - (cx, cy)), pr.rho, places=6)
        self.assertGreater(pr.rho, 0)

    def test_invalid_parameters_raise(self):
        with self.assertRaises(gears.GearError):
            gears.profile(GearParams(module=0))
        with self.assertRaises(gears.GearError):
            gears.profile(GearParams(teeth=6, shift=1.5))
        checks, prof = gears.check(GearParams(kind='spur_int', teeth=20))
        self.assertIsNone(prof)
        self.assertIn('error', [c.level for c in checks])
        checks, prof = gears.check(GearParams(teeth=20))
        self.assertEqual(checks, [])
        self.assertIsNotNone(prof)


class GearOccTests(unittest.TestCase):
    """Zarys w Open CASCADE: dokładność krzywych, ciągłość, zamknięcie, wymiary."""

    @classmethod
    def setUpClass(cls):
        from rccad.gears import occ
        cls.occ = occ

    def test_spline_follows_the_exact_involute_and_its_normal_touches_the_base_circle(self):
        from OCP.BRep import BRep_Tool
        from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
        from OCP.gp import gp_Pnt, gp_Vec
        p = GearParams(module=2, teeth=20)
        pr, g = gears.profile(p), derived(p)
        edge = self.occ.spline_edge(pr.flank, pr.flank_tangents)
        curve = BRep_Tool.Curve_s(edge, 0.0, 0.0)
        rb, at = g['db'] / 2, math.radians(g['alpha_t'])
        for R in np.linspace(pr.r_form + 1e-6, g['da'] / 2, 97):                     # punkty dokładne między węzłami
            t = g['s'] / g['d'] + gears.inv(at) - gears.inv(math.acos(rb / R))
            proj = GeomAPI_ProjectPointOnCurve(gp_Pnt(R * math.cos(t), R * math.sin(t), 0), curve)
            self.assertLess(proj.LowerDistance(), 1e-6)
            pnt, vec = gp_Pnt(), gp_Vec()
            curve.D1(proj.LowerDistanceParameter(), pnt, vec)
            # normalna ewolwenty jest styczna do okręgu zasadniczego: odległość środka od stycznej = sqrt(R² - rb²)
            d = abs(pnt.X() * vec.Y() - pnt.Y() * vec.X()) / vec.Magnitude()
            self.assertLess(abs(d - math.sqrt(R * R - rb * rb)), 1e-5 * R)

    def test_tooth_wire_is_continuous_symmetric_and_tangent_at_the_root(self):
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        p = GearParams(module=2, teeth=30)
        edges = self.occ.tooth_edges(gears.profile(p))
        wire = self.occ.tooth_wire(p)
        self.assertEqual(len(wire.Edges()), 5)
        bb = wire.BoundingBox()
        self.assertAlmostEqual(bb.ymin, -bb.ymax, places=9)                          # symetria względem osi zęba
        def tangent(edge, end):
            c = BRepAdaptor_Curve(edge)
            u = c.LastParameter() if end else c.FirstParameter()
            v = c.DN(u, 1)
            return np.array((v.X(), v.Y())) / v.Magnitude()
        # przejście stopy -> ewolwenta: styczne (G1); ewolwenta -> wierzchołek: naroże
        self.assertGreater(float(np.dot(tangent(edges[3], True), tangent(edges[4], False))), math.cos(math.radians(.05)))
        self.assertGreater(float(np.dot(tangent(edges[0], True), tangent(edges[1], False))), math.cos(math.radians(.05)))
        self.assertLess(float(np.dot(tangent(edges[1], True), tangent(edges[2], False))), math.cos(math.radians(5)))

    def test_outline_closed_valid_with_exact_diameters_and_area(self):
        for kw in (dict(teeth=20), dict(teeth=8), dict(kind='helical_ext', teeth=33, helix=15, shift=.2),
                   dict(kind='spur_int', teeth=60), dict(kind='helical_int', teeth=50, helix=20, hand='left')):
            p = GearParams(**kw)
            g = derived(p)
            wire = self.occ.outline_wire(p)
            self.assertTrue(wire.IsClosed(), kw)
            self.assertTrue(wire.isValid(), kw)
            R = [math.hypot(v.x, v.y) for e in wire.Edges() for v in e.positions(np.linspace(0, 1, 9))]
            lo, hi = sorted((g['da'] / 2, g['df'] / 2))
            self.assertAlmostEqual(min(R), lo, places=6, msg=kw)
            self.assertAlmostEqual(max(R), hi, places=6, msg=kw)
            face = self.occ.section_face(p)
            self.assertTrue(face.isValid(), kw)
            area = gears.polygon_area(gears.outline_points(p, 600))
            if p.internal:
                area = math.pi * (g['rim'] / 2) ** 2 - area
            self.assertAlmostEqual(face.Area() / area, 1, places=4, msg=kw)

    def test_tooth_thickness_on_the_pitch_circle(self):
        import cadquery as cq
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        for kw in (dict(teeth=24, shift=.25, backlash=.1), dict(kind='helical_ext', teeth=24, helix=25)):
            p = GearParams(**kw)
            g = derived(p)
            edges = self.occ.tooth_edges(gears.profile(p))
            circle = cq.Edge.makeCircle(g['d'] / 2)
            dist = BRepExtrema_DistShapeShape(edges[3], circle.wrapped)
            self.assertLess(dist.Value(), 1e-9)
            pnt = dist.PointOnShape1(1)
            self.assertAlmostEqual(2 * math.atan2(pnt.Y(), pnt.X()) * g['d'] / 2, g['s'], places=6)    # łuk grubości zęba

    def test_large_gear_is_fast(self):
        import time
        start = time.perf_counter()
        face = self.occ.section_face(GearParams(module=1, teeth=150))
        self.assertTrue(face.isValid())
        self.assertLess(time.perf_counter() - start, 10)


if __name__ == '__main__':
    unittest.main()
