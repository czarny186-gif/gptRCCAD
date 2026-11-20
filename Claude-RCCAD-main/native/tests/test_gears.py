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
        self.assertAlmostEqual(g['rim'], 125 + 2 * 1.2 * 4.5)          # wieniec dobrany sam: obręcz 1,2·h (ISO 6336-3)
        self.assertAlmostEqual(g['rim_thickness'], 1.2 * 4.5)
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
        code = ('import sys; sys.path.insert(0, "."); import rccad.gears, rccad.gears.preview, rccad.gears.pair, rccad.gears.kinematics; '
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


class GearSolidTests(unittest.TestCase):
    """Etap 3: pełna bryła koła o zębach prostych - poprawność, szczelność, objętość, otwór, piasta, rowek, STEP."""

    @classmethod
    def setUpClass(cls):
        from rccad.gears import occ
        cls.occ = occ

    def check(self, p):
        solid = self.occ.gear_solid(p)
        report = self.occ.solid_report(solid)
        self.assertTrue(report['ok'], report)
        self.assertEqual(solid.ShapeType(), 'Solid')
        return solid

    def section_area(self, p):
        return self.occ.section_face(p).Area()

    def test_plain_gear_is_one_prism_with_exact_volume_and_diameters(self):
        p = GearParams(module=2, teeth=20, width=12)
        solid = self.check(p)
        self.assertAlmostEqual(solid.Volume(), self.section_area(p) * 12, delta=1e-6 * solid.Volume())
        bb = solid.BoundingBox()
        self.assertAlmostEqual(bb.zmin, 0, places=6)                        # pudełko OCC poszerzone o tolerancję 1e-7
        self.assertAlmostEqual(bb.zmax, 12, places=6)
        self.assertAlmostEqual(bb.xmax, 22, places=6)                     # pierwszy ząb na +X: wierzchołek na r_a
        self.assertEqual(len(solid.Faces()), 20 * 6 + 2)                    # 5 ścian zęba + dno wrębu, dwie płaskie

    def test_bore_keyway_and_hub(self):
        base = dict(module=2, teeth=20, width=10)
        bore = self.check(GearParams(bore=10, **base))
        self.assertAlmostEqual(bore.Volume(), self.section_area(GearParams(**base)) * 10 - math.pi * 25 * 10, delta=1e-6 * bore.Volume())
        key = self.check(GearParams(bore=10, keyway=True, **base))
        b, t2 = gears.keyway_standard(10)
        self.assertEqual((b, t2), (3.0, 1.4))
        x0 = math.sqrt(25 - 1.5 ** 2)
        segment = 25 * math.asin(1.5 / 5) - 1.5 * x0                         # odcinek koła pod rowkiem
        key_area = 3 * (5 + t2 - x0) - segment
        self.assertAlmostEqual(bore.Volume() - key.Volume(), key_area * 10, delta=1e-6 * bore.Volume())
        self.assertAlmostEqual(key.BoundingBox().xmax, 22, places=6)
        hub = self.check(GearParams(bore=10, keyway=True, hub=True, hub_diameter=24, hub_length=8, **base))
        ring = math.pi * (12 ** 2 - 5 ** 2) - key_area
        self.assertAlmostEqual(hub.Volume() - key.Volume(), ring * 8, delta=1e-6 * hub.Volume())
        self.assertAlmostEqual(hub.BoundingBox().zmax, 18, places=6)
        bores = [f for f in hub.Faces() if f.geomType() == 'CYLINDER' and abs(f._geomAdaptor().Cylinder().Radius() - 5) < 1e-9]
        self.assertEqual(len(bores), 1)                                       # otwór przez wieniec i piastę - jedna ściana
        self.assertAlmostEqual(bores[0].BoundingBox().zmax - bores[0].BoundingBox().zmin, 18, places=6)

    def test_wide_hub_covering_the_teeth_uses_one_union(self):
        p = GearParams(module=2, teeth=20, bore=10, hub=True, hub_diameter=40, hub_length=5)
        solid = self.check(p)
        teeth = self.section_area(GearParams(module=2, teeth=20)) * 10 - math.pi * 25 * 10
        self.assertAlmostEqual(solid.Volume(), teeth + math.pi * (400 - 25) * 5, delta=1e-6 * solid.Volume())

    def test_internal_spur_gear_ring(self):
        p = GearParams(kind='spur_int', module=2, teeth=60, width=15, rim_diameter=140)
        solid = self.check(p)
        self.assertAlmostEqual(solid.Volume(), self.section_area(p) * 15, delta=1e-6 * solid.Volume())
        self.assertAlmostEqual(solid.BoundingBox().xmax, 70, places=6)

    def test_undercut_and_many_teeth(self):
        self.check(GearParams(module=2, teeth=8, bore=4))
        import time
        start = time.perf_counter()
        self.check(GearParams(module=1, teeth=150, bore=20, keyway=True, hub=True, hub_diameter=40, hub_length=10))
        self.assertLess(time.perf_counter() - start, 15)

    def test_no_boolean_per_tooth(self):
        """Zęby i otwór powstają bez operacji logicznych; piasta węższa niż stopy - też bez nich (zszycie)."""
        from unittest.mock import patch
        import OCP.BRepAlgoAPI as algo
        calls = []
        real = algo.BRepAlgoAPI_Fuse
        with patch.object(algo, 'BRepAlgoAPI_Fuse', side_effect=lambda *a: calls.append(1) or real(*a)):
            self.check(GearParams(module=2, teeth=40, bore=10, keyway=True, hub=True, hub_diameter=24, hub_length=8))
            self.assertEqual(calls, [])
            self.check(GearParams(module=2, teeth=20, bore=10, hub=True, hub_diameter=40, hub_length=5))
            self.assertEqual(len(calls), 1)                                   # piasta szersza niż stopy: jedna suma

    def test_reversed_solid_is_rejected(self):
        solid = self.check(GearParams(module=2, teeth=20))
        import cadquery as cq
        reversed_solid = cq.Shape.cast(solid.wrapped.Reversed())
        self.assertFalse(self.occ.solid_report(reversed_solid)['ok'])


    def test_step_export_round_trip(self):
        import tempfile
        from rccad import kernel
        p = GearParams(module=1.5, teeth=24, width=8, bore=8, keyway=True, hub=True, hub_diameter=16, hub_length=6)
        solid = self.check(p)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'kolo.step')
            kernel.export_shapes([solid], path)
            back = kernel.import_shapes(path)
        self.assertEqual([kind for _, kind in back], ['solid'])
        shape = back[0][0]
        self.assertTrue(self.occ.solid_report(shape)['ok'])
        self.assertAlmostEqual(shape.Volume(), solid.Volume(), delta=1e-6 * solid.Volume())
        self.assertEqual(len(shape.Faces()), len(solid.Faces()))

    def test_keyway_validation(self):
        self.assertIn(('error', 'bore'), levels(validate(GearParams(keyway=True))))
        self.assertIn(('error', 'key_width'), levels(validate(GearParams(bore=4, keyway=True))))      # poza tablicą DIN
        self.assertEqual(validate(GearParams(bore=4, keyway=True, key_width=1.5, key_depth=.8)), [])
        self.assertIn(('error', 'key_depth'), levels(validate(GearParams(module=2, teeth=20, bore=20, keyway=True, key_depth=6))))
        self.assertIn(('error', 'key_width'), levels(validate(GearParams(module=2, teeth=20, bore=10, keyway=True, key_width=9))))
        self.assertIn(('error', 'key_depth'), levels(validate(GearParams(module=2, teeth=30, bore=10, keyway=True, hub=True,
                                                                         hub_diameter=13, hub_length=5))))
        self.assertEqual(gears.keyway_standard(30), (8.0, 3.3))
        self.assertEqual(gears.keyway_standard(30.5), (10.0, 3.3))
        self.assertIsNone(gears.keyway_standard(200))


KIND_CASES = {
    'spur_ext': dict(kind='spur_ext', module=2, teeth=20, width=12, bore=10, keyway=True, hub=True, hub_diameter=24, hub_length=6),
    'helical_ext': dict(kind='helical_ext', module=2, teeth=20, width=16, helix=20, hand='right', bore=10, keyway=True,
                        hub=True, hub_diameter=24, hub_length=6),
    'spur_int': dict(kind='spur_int', module=2, teeth=60, width=12, rim_diameter=140),
    'helical_int': dict(kind='helical_int', module=1.5, teeth=56, width=14, helix=15, hand='left', shift=.2, rim_diameter=100),
}


class GearKindsTests(unittest.TestCase):
    """Etap 4: wszystkie cztery rodzaje uzębienia - bryła B-Rep, dokładne boki (ewolwenta / ewolwentowa powierzchnia
    śrubowa), objętość, kierunek skrętu, obręcz koła wewnętrznego, STEP."""

    @classmethod
    def setUpClass(cls):
        from rccad.gears import occ
        cls.occ = occ
        cls.solids = {kind: occ.gear_solid(GearParams(**kw)) for kind, kw in KIND_CASES.items()}

    def flank_distance(self, solid, p, angle_sign=1.0):
        """Największa odległość punktów dokładnego boku zęba (przekrój czołowy obrócony o kąt skrętu na wysokości z) od bryły."""
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        from OCP.gp import gp_Pnt
        prof, twist, width = gears.profile(p), self.occ.twist_angle(p) * angle_sign, p.width
        worst = 0.0
        shell = solid.Shells()[0].wrapped
        for z in np.linspace(0, width, 5):
            a = twist * z / width
            for x, y in list(prof.flank[::6]) + list(gears.ToothProfile.mirrored(prof.flank)[::6]):
                X, Y = x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)
                dist = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(X, Y, z)).Vertex(), shell)
                worst = max(worst, dist.Value())
        return worst

    def test_all_kinds_are_valid_closed_solids(self):
        for kind, solid in self.solids.items():
            report = self.occ.solid_report(solid)
            self.assertTrue(report['ok'], (kind, report))
            self.assertEqual(solid.ShapeType(), 'Solid', kind)
            for face in solid.Faces():                                       # B-Rep z powierzchni, nie siatka trójkątów
                self.assertNotEqual(face.geomType(), 'OTHER', kind)

    def test_volume_is_section_times_width(self):
        """Skręt przekroju nie zmienia objętości: wieniec = przekrój czołowy × szerokość (+ piasta, - otwór z rowkiem)."""
        for kind, kw in KIND_CASES.items():
            p = GearParams(**kw)
            volume = self.occ.section_face(p).Area() * p.width
            if not p.internal:
                bore = self.occ.plane_face(self.occ.bore_wire(p)).Area()
                volume += -bore * p.width + (math.pi * (p.hub_diameter / 2) ** 2 - bore) * p.hub_length
            self.assertAlmostEqual(self.solids[kind].Volume() / volume, 1, places=5, msg=kind)

    def test_flanks_are_exact_involute_helicoids(self):
        for kind, kw in KIND_CASES.items():
            p = GearParams(**kw)
            self.assertLess(self.flank_distance(self.solids[kind], p), 1e-5, kind)

    def test_hand_of_helix(self):
        for kind in ('helical_ext', 'helical_int'):
            p = GearParams(**KIND_CASES[kind])
            self.assertGreater(self.flank_distance(self.solids[kind], p, -1.0), 1e-2, kind)   # przeciwny skręt - nie ta bryła
        right = GearParams(**dict(KIND_CASES['helical_ext'], hand='right'))
        left = GearParams(**dict(KIND_CASES['helical_ext'], hand='left'))
        self.assertGreater(self.occ.twist_angle(right), 0)
        self.assertAlmostEqual(self.occ.twist_angle(left), -self.occ.twist_angle(right))
        self.assertEqual(self.occ.twist_angle(GearParams(**KIND_CASES['spur_ext'])), 0)

    def test_lead_and_twist(self):
        p = GearParams(kind='helical_ext', module=3, teeth=31, helix=18, width=40)
        d = 31 * 3 / math.cos(math.radians(18))
        L = math.pi * d / math.tan(math.radians(18))
        self.assertAlmostEqual(self.occ.lead(p), L)
        self.assertAlmostEqual(self.occ.twist_angle(p), 2 * math.pi * 40 / L)
        self.assertIsNone(self.occ.lead(GearParams()))

    def test_tip_and_root_diameters(self):
        for kind, kw in KIND_CASES.items():
            p = GearParams(**kw)
            g = derived(p)
            bb = self.solids[kind].BoundingBox()
            outer = g['rim'] if p.internal else g['da']
            self.assertLess(abs(max(bb.xmax, bb.ymax, -bb.xmin, -bb.ymin) - outer / 2), 1e-3, kind)
            self.assertAlmostEqual(bb.zmin, 0, places=6)

    def test_straight_bore_and_keyway_in_helical_gear_without_booleans(self):
        from unittest.mock import patch
        import OCP.BRepAlgoAPI as algo
        solid = self.solids['helical_ext']
        bores = [f for f in solid.Faces() if f.geomType() == 'CYLINDER' and abs(f._geomAdaptor().Cylinder().Radius() - 5) < 1e-9]
        self.assertEqual(len(bores), 1)                                      # otwór prosty przez wieniec i piastę
        self.assertAlmostEqual(bores[0].BoundingBox().zmax - bores[0].BoundingBox().zmin, 22, places=6)
        keyway = [f for f in solid.Faces() if f.geomType() == 'PLANE' and abs(f.normalAt(f.Center()).z) < 1e-9
                  and abs(abs(f.normalAt(f.Center()).y) - 1) < 1e-9]
        self.assertEqual(len(keyway), 2)                                      # boki rowka - płaskie, równoległe do osi
        calls = []
        real = algo.BRepAlgoAPI_Fuse
        with patch.object(algo, 'BRepAlgoAPI_Fuse', side_effect=lambda *a: calls.append(1) or real(*a)):
            self.occ.gear_solid(GearParams(**KIND_CASES['helical_ext']))
            self.occ.gear_solid(GearParams(**KIND_CASES['helical_int']))
        self.assertEqual(calls, [])

    def test_internal_rim_thickness_control(self):
        base = dict(kind='helical_int', module=2, teeth=60, helix=15)
        g = derived(GearParams(**base))
        need = 1.2 * g['height']
        self.assertIn(('error', 'rim_diameter'), levels(validate(GearParams(rim_diameter=g['df'] + 1.5 * 2, **base))))
        self.assertIn(('warning', 'rim_diameter'), levels(validate(GearParams(rim_diameter=g['df'] + 2 * need - .1, **base))))
        self.assertEqual(validate(GearParams(rim_diameter=g['df'] + 2 * need + .1, **base)), [])
        self.assertEqual(validate(GearParams(**base)), [])                    # dobrany sam - pełna nośność
        self.assertAlmostEqual(derived(GearParams(**base))['rim_thickness'], need)

    def test_step_export_of_every_kind(self):
        import tempfile
        from rccad import kernel
        with tempfile.TemporaryDirectory() as folder:
            for kind, solid in self.solids.items():
                path = os.path.join(folder, f'{kind}.step')
                kernel.export_shapes([solid], path)
                back = kernel.import_shapes(path)
                self.assertEqual([k for _, k in back], ['solid'], kind)
                shape = back[0][0]
                self.assertTrue(self.occ.solid_report(shape)['ok'], kind)
                self.assertAlmostEqual(shape.Volume() / solid.Volume(), 1, places=6, msg=kind)
                self.assertEqual(len(shape.Faces()), len(solid.Faces()), kind)


class GearPreviewTests(unittest.TestCase):
    """Etap 5: szybki podgląd (siatka z silnika) - ten sam kształt co bryła B-Rep, liczony wielokrotnie szybciej."""

    @classmethod
    def setUpClass(cls):
        from rccad.gears import occ, preview
        cls.occ, cls.preview = occ, preview

    def test_preview_matches_the_exact_solid_for_every_kind(self):
        import manifold3d as mf
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        from OCP.gp import gp_Pnt
        for kind, kw in KIND_CASES.items():
            p = GearParams(**kw)
            v, t = self.preview.mesh_arrays(p)
            mesh = mf.Manifold(mf.Mesh(vert_properties=v.astype(np.float32), tri_verts=t.astype(np.uint32)))
            solid = self.occ.gear_solid(p)
            self.assertLess(abs(mesh.volume() / solid.Volume() - 1), 5e-3, kind)
            shell = solid.Shells()[0].wrapped
            g = derived(p)
            lo, hi = sorted((g['da'] / 2, g['df'] / 2))
            R = np.hypot(v[:, 0], v[:, 1])
            teeth = (R > lo - 1e-6) & (R < hi + 1e-6)                        # wierzchołki zarysu zębów (nie okręgi otworu / piasty)
            for z in (0.0, p.width):                                        # dno i góra (skręt) leżą na bryle
                ring = v[(np.abs(v[:, 2] - z) < 1e-6) & teeth][::25][:60]
                self.assertGreater(len(ring), 10)
                worst = max(BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, q))).Vertex(), shell).Value()
                            for q in ring)
                self.assertLess(worst, 1e-3, (kind, z))

    def test_preview_is_fast(self):
        import time
        for kw in (dict(teeth=200, module=1, bore=20, keyway=True, hub=True, hub_diameter=40, hub_length=10),
                   dict(kind='helical_ext', teeth=40, helix=30, width=40), dict(kind='helical_int', teeth=120, helix=20)):
            start = time.perf_counter()
            self.preview.mesh_arrays(GearParams(**kw))
            self.assertLess(time.perf_counter() - start, .5, kw)

    def test_fewer_outline_points_keep_curve_ends(self):
        p = GearParams(teeth=20)
        dense, sparse = gears.outline_points(p), gears.outline_points(p, 5)
        self.assertLess(len(sparse), len(dense) / 3)
        R = np.hypot(*sparse.T)
        g = derived(p)
        self.assertAlmostEqual(R.max(), g['da'] / 2, places=9)
        self.assertAlmostEqual(R.min(), g['df'] / 2, places=9)


class GearRebuildTests(unittest.TestCase):
    """Etap 5: krok historii 'gear' - pamięć brył (przebudowa tylko zmienionych kół), przebudowa koła bez kroku tworzącego,
    położenie koła zapamiętane przy ruchu sztywnym."""

    def test_unchanged_gear_is_not_rebuilt(self):
        from rccad import history as hist
        import time
        p = GearParams(kind='helical_ext', teeth=37, helix=21, width=11)
        first = hist.gear_shape(p)
        start = time.perf_counter()
        again = hist.gear_shape(GearParams.from_dict(p.to_dict()))
        self.assertIs(again, first)
        self.assertLess(time.perf_counter() - start, .01)
        self.assertIsNot(hist.gear_shape(GearParams(kind='helical_ext', teeth=38, helix=21, width=11)), first)

    def test_placement_is_tracked_and_rebuild_keeps_it(self):
        from rccad import history as hist, kernel
        bodies = hist.run_gear([], dict(type='gear', params=GearParams(teeth=20, bore=8).to_dict(), out=['g1']))
        bodies = hist.run_transform(bodies, dict(type='transform', id='g1', mode='move', v=[40.0, 5.0, 3.0]))
        bodies = hist.run_transform(bodies, dict(type='transform', id='g1', mode='rotate', v=[90.0, 0.0, 0.0]))
        body = bodies[0]
        place = np.asarray(body.meta['gear_place'], float)
        expected = hist.apply_placement(hist.gear_shape(GearParams(teeth=20, bore=8)), place)
        self.assertAlmostEqual(expected.Volume(), body.shape.Volume(), delta=1e-6 * body.shape.Volume())
        np.testing.assert_allclose(np.array(expected.Center().toTuple()), np.array(body.shape.Center().toTuple()), atol=1e-6)
        out = hist.run_gear(bodies, dict(type='gear', params=GearParams(teeth=30, bore=8).to_dict(), replace='g1',
                                         place=body.meta['gear_place']))
        new = out[0]
        self.assertEqual((new.id, new.name, new.meta['gear']['teeth']), ('g1', 'Koło z30 m2', 30))
        np.testing.assert_allclose(np.array(new.shape.Center().toTuple()), np.array(body.shape.Center().toTuple()), atol=1e-6)
        self.assertEqual(hist.reads(dict(type='gear', params={}, replace='g1'), out), {'g1'})
        self.assertEqual(hist.reads(dict(type='gear', params={}, out=['g2']), out), set())
        renamed = [type(new)(**{**new.__dict__, 'name': 'Napęd'})]
        out = hist.run_gear(renamed, dict(type='gear', params=GearParams(teeth=25, bore=8).to_dict(), replace='g1'))
        self.assertEqual(out[0].name, 'Napęd')                                    # własna nazwa zostaje


PAIR_CASES = {
    'standard': dict(teeth1=20, teeth2=40),
    'undercut_pinion': dict(teeth1=12, teeth2=40),
    'given_center': dict(teeth1=20, teeth2=40, center=61),
    'ratio': dict(teeth1=17, by_ratio=True, ratio=2.5),
    'helical': dict(teeth1=18, teeth2=36, helix=20, hand='left'),
    'ring': dict(kind='internal', teeth1=20, teeth2=60),
    'ring_helical': dict(kind='internal', teeth1=18, teeth2=72, helix=15, center=57),
}


class GearPairTests(unittest.TestCase):
    """Etap 6: para kół - przełożenie, odległość osi, korekcje, kierunki skrętu, położenie w zazębieniu, kontrola."""

    @classmethod
    def setUpClass(cls):
        from rccad.gears import pair
        cls.pair = pair

    def solve(self, **kw):
        return self.pair.solve(self.pair.PairParams(**kw))

    def test_ratio_teeth_and_hands(self):
        r = self.solve(**PAIR_CASES['ratio'])
        self.assertEqual(r.z2, 42)                                         # 2,5 · 17 = 42,5 -> 42
        self.assertAlmostEqual(r.ratio, 42 / 17)
        self.assertEqual([c.field for c in r.checks if c.level == 'warning'], [])
        far = self.solve(teeth1=17, by_ratio=True, ratio=2.53)
        self.assertEqual(far.z2, 43)
        r = self.solve(**PAIR_CASES['helical'])
        self.assertEqual((r.gear1.hand, r.gear2.hand, r.gear1.kind, r.gear2.kind), ('left', 'right', 'helical_ext', 'helical_ext'))
        r = self.solve(**PAIR_CASES['ring_helical'])
        self.assertEqual((r.gear1.hand, r.gear2.hand, r.gear2.kind), ('right', 'right', 'helical_int'))
        r = self.solve(**PAIR_CASES['ring'])
        self.assertEqual((r.gear1.kind, r.gear2.kind), ('spur_ext', 'spur_int'))

    def test_standard_pair_numbers(self):
        r = self.solve(**PAIR_CASES['standard'], backlash=0)
        self.assertTrue(r.ok, r.checks)
        self.assertAlmostEqual(r.center, 60)
        self.assertAlmostEqual(r.alpha_w, 20)
        rb1, rb2 = 20 * math.cos(math.radians(20)), 40 * math.cos(math.radians(20))
        eps = (math.sqrt(22 ** 2 - rb1 ** 2) + math.sqrt(42 ** 2 - rb2 ** 2) - 60 * math.sin(math.radians(20))) / (2 * math.pi * math.cos(math.radians(20)))
        self.assertAlmostEqual(r.contact_ratio, eps)
        self.assertAlmostEqual(r.clearance1, .5)                            # 0,25·m
        np.testing.assert_allclose(np.array(r.place2)[:, 3], (60, 0, 0))
        h = self.solve(**PAIR_CASES['helical'])
        self.assertAlmostEqual(h.center, 2 * (18 + 36) / 2 / math.cos(math.radians(20)))
        self.assertAlmostEqual(h.overlap_ratio, 10 * math.sin(math.radians(20)) / (2 * math.pi))

    def test_profile_shift_choices(self):
        r = self.solve(**PAIR_CASES['undercut_pinion'])                  # P-0: zębnik bez podcięcia, odległość bez zmian
        self.assertTrue(r.ok, r.checks)
        self.assertAlmostEqual(r.gear1.shift, -r.gear2.shift)
        self.assertGreater(r.gear1.shift, 0)
        self.assertFalse(derived(r.gear1)['undercut'])
        self.assertAlmostEqual(r.center, r.center0)
        r = self.solve(**PAIR_CASES['given_center'])
        self.assertAlmostEqual(r.center, 61)
        a0, at = 60, math.radians(20)
        self.assertAlmostEqual(math.cos(math.radians(r.alpha_w)), a0 * math.cos(at) / 61)
        sum_x = (gears.inv(math.radians(r.alpha_w)) - gears.inv(at)) * 60 / (2 * math.tan(at))
        self.assertAlmostEqual(r.gear1.shift + r.gear2.shift, sum_x, places=5)     # wzór na sumę korekcji (ISO 21771)
        r = self.solve(**PAIR_CASES['ring'])                               # wieniec: korekcja usuwająca interferencję
        self.assertTrue(r.ok, r.checks)
        self.assertGreater(r.gear2.shift, 0)

    def mesh_gap(self, r):
        """Najmniejszy odstęp zarysów obu kół w strefie zazębienia na przekrojach z = 0, b/2, b (zęby skośne: przekroje
        obrócone o skręt) - zarysy krzywymi Open CASCADE, w wyliczonych położeniach. Ujemny - zarysy się przecinają."""
        import cadquery as cq
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        from rccad.gears import occ
        a, width = r.center, r.params.width
        rw1 = a * r.gear1.teeth / (r.z2 - r.gear1.teeth if r.params.internal else r.z2 + r.gear1.teeth)
        pitch = np.array((a + rw1, 0.0) if r.params.internal else (rw1, 0.0))
        worst = None
        for z in (0.0, width / 2, width):
            near = []
            for g, place in ((r.gear1, r.place1), (r.gear2, r.place2)):
                wire = occ.outline_wire(g).rotate(cq.Vector(), cq.Vector(0, 0, 1), math.degrees(occ.twist_angle(g) * z / width))
                M = np.asarray(place, float)
                edges = []
                for e in wire.Edges():
                    pts = np.array([v.toTuple()[:2] for v in e.positions(np.linspace(0, 1, 5))]) @ M[:2, :2].T + M[:2, 3]
                    if np.min(np.linalg.norm(pts - pitch, axis=1)) < 4 * r.params.module:
                        edges.append(e)
                trsf = cq.Matrix([[*M[0, :3], M[0, 3]], [*M[1, :3], M[1, 3]], [*M[2, :3], z]])
                near.append(cq.Compound.makeCompound(edges).transformGeometry(trsf))
            gap = BRepExtrema_DistShapeShape(near[0].wrapped, near[1].wrapped).Value()
            worst = gap if worst is None else min(worst, gap)
        return worst

    def test_gears_mesh_with_the_set_backlash(self):
        """Zarysy obu kół w wyliczonych położeniach: odstęp boków z każdej strony zęba = j·cos α / 2 (ząb pośrodku wrębu),
        także dla zębów skośnych na całej szerokości (kierunki skrętu) i dla wieńca."""
        for name, kw in PAIR_CASES.items():
            r = self.solve(**kw, backlash=.1)
            self.assertTrue(r.ok, (name, r.checks))
            beta = math.radians(r.params.helix)
            alpha_t = math.atan(math.tan(math.radians(20)) / math.cos(beta))
            beta_b = math.atan(math.tan(beta) * math.cos(alpha_t))         # w przekroju czołowym odstęp większy o 1 / cos βb
            self.assertAlmostEqual(self.mesh_gap(r), .1 * math.cos(math.radians(20)) / 2 / math.cos(beta_b), delta=2e-4, msg=name)
        r = self.solve(**PAIR_CASES['standard'], backlash=0)               # bez luzu: zęby się stykają
        self.assertLess(self.mesh_gap(r), 1e-5)
        wrong = self.solve(**PAIR_CASES['helical'], backlash=.1)            # ten sam kierunek skrętu w parze zewnętrznej - kolizja
        wrong.gear2.hand = wrong.gear1.hand
        self.assertLess(self.mesh_gap(wrong), 1e-6)

    def test_solids_of_a_pair_do_not_overlap(self):
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        from rccad import history as hist
        r = self.solve(**PAIR_CASES['ring'], backlash=.1)
        s1 = hist.apply_placement(hist.gear_shape(r.gear1), np.array(r.place1))
        s2 = hist.apply_placement(hist.gear_shape(r.gear2), np.array(r.place2))
        self.assertGreater(BRepExtrema_DistShapeShape(s1.wrapped, s2.wrapped).Value(), .04)

    def test_interference_and_other_checks(self):
        r = self.solve(kind='internal', teeth1=20, teeth2=60, auto_shift=False)
        self.assertIn('Interferencja', ' '.join(c.message for c in r.checks if c.level == 'error'))
        r = self.solve(teeth1=12, teeth2=40, auto_shift=False)               # bez korekcji: podcięcie zębnika, interferencja
        self.assertTrue(any(c.level == 'error' and 'Interferencja' in c.message for c in r.checks))
        self.assertTrue(any('Podcięcie' in c.message for c in r.checks))
        r = self.solve(teeth1=20, teeth2=40, center=63, auto_shift=False, shift1=.5)
        self.assertTrue(any(c.level == 'warning' and 'luz wierzchołkowy' in c.message.lower() for c in r.checks))
        r = self.solve(teeth1=20, teeth2=40, center=64, auto_shift=False, shift1=.5)
        self.assertTrue(any(c.level == 'error' and 'uderzają' in c.message for c in r.checks))
        r = self.solve(kind='internal', teeth1=20, teeth2=26)
        self.assertTrue(any(c.level == 'warning' and 'różnica liczby zębów' in c.message for c in r.checks))
        with self.assertRaises(gears.GearError):
            self.solve(teeth1=20, teeth2=40, center=90)
        with self.assertRaises(gears.GearError):
            self.solve(kind='internal', teeth1=20, teeth2=21)

    def test_history_step_creates_both_gears(self):
        from rccad import history as hist
        params = self.pair.PairParams(**PAIR_CASES['ring']).to_dict()
        out = hist.run_gear_pair([], dict(type='gear_pair', params=params, out=['p', 'r']))
        self.assertEqual([b.id for b in out], ['p', 'r'])
        self.assertEqual(out[0].folder, 'Para kół z20/z60')
        self.assertEqual(out[1].name, 'Wieniec z60 m2')
        self.assertEqual(out[0].meta['gear_pair']['role'], 1)
        self.assertEqual(hist.reads(dict(type='gear_pair', params=params, out=['p', 'r']), out), set())
        r = self.pair.solve(self.pair.PairParams(**PAIR_CASES['ring']))
        c = out[0].shape.Center()
        self.assertAlmostEqual(math.hypot(c.x, c.y), r.center, places=5)      # zębnik w odległości osi od środka wieńca


class GearKinematicsTests(unittest.TestCase):
    """Etap 7: symulacja - kąty w przełożeniu, obrót wokół własnych osi (stała odległość osi), faza zębów, kolizje."""

    @classmethod
    def setUpClass(cls):
        from rccad.gears import kinematics, pair
        cls.km, cls.pair = kinematics, pair

    def sim(self, **kw):
        r = self.pair.solve(self.pair.PairParams(**kw))
        m4 = lambda place: np.vstack([np.asarray(place, float), [0, 0, 0, 1]])
        return self.km.Simulation(self.km.Wheel('a', r.gear1, m4(r.place1)), self.km.Wheel('b', r.gear2, m4(r.place2))), r

    def test_angles_follow_the_ratio_and_kind(self):
        sim, _ = self.sim(teeth1=20, teeth2=50)
        self.assertEqual(sim.angles(0, 1.0), (1.0, -.4))                    # para zewnętrzna: przeciwnie
        self.assertEqual(sim.angles(1, 1.0), (-2.5, 1.0))
        self.assertEqual(sim.speeds(0, 100), (40.0, False))
        sim, _ = self.sim(kind='internal', teeth1=20, teeth2=60)
        self.assertAlmostEqual(sim.angles(0, 1.0)[1], 1 / 3)               # z wieńcem: w tę samą stronę
        self.assertEqual(sim.speeds(1, 30), (90.0, True))

    def test_rotation_keeps_axes_fixed(self):
        sim, r = self.sim(teeth1=18, teeth2=36, helix=20)
        mats = sim.matrices(*sim.angles(0, .7))
        for wheel in sim.wheels:
            M = mats[wheel.id]
            c = wheel.place[:3, 3]
            np.testing.assert_allclose(M[:3, :3] @ c + M[:3, 3], c, atol=1e-12)                 # środek koła stoi
            np.testing.assert_allclose(M[:3, :3] @ sim.axis, sim.axis, atol=1e-12)            # oś się nie zmienia
            self.assertAlmostEqual(np.linalg.det(M[:3, :3]), 1)
        a = mats['a'] @ np.append(sim.wheels[0].place[:3, 3], 1)
        b = mats['b'] @ np.append(sim.wheels[1].place[:3, 3], 1)
        self.assertAlmostEqual(np.linalg.norm(a - b), r.center)

    def test_no_collision_over_a_whole_pitch_and_after_many_turns(self):
        """Faza zębów: przez całą podziałkę i po wielu obrotach odstęp zębów zostaje równy luzowi (j·cos α / 2)."""
        for kw in (dict(teeth1=20, teeth2=40), dict(teeth1=12, teeth2=40), dict(teeth1=18, teeth2=36, helix=20),
                   dict(kind='internal', teeth1=20, teeth2=60), dict(kind='internal', teeth1=18, teeth2=72, helix=15, center=57)):
            sim, r = self.sim(backlash=.1, **kw)
            overlap, gap = sim.sweep(0, 16)
            self.assertLess(overlap, self.km.OVERLAP_TOL, kw)
            self.assertGreater(gap, .04, kw)
            far = sim.check(*sim.angles(1, 7.3 * 2 * math.pi + .123))           # 7 obrotów koła 2
            self.assertFalse(far['collision'], kw)
            self.assertGreater(far['gap'], .04, kw)

    def test_wrong_phase_or_position_is_a_collision(self):
        sim, r = self.sim(teeth1=20, teeth2=40, backlash=.1)
        self.assertTrue(sim.check(0.0, math.pi / 40)['collision'])            # koło 2 obrócone o pół podziałki
        closer = sim.wheels[1].place.copy()
        closer[0, 3] -= .6                                                     # osie bliżej o 0,6 mm
        moved = self.km.Simulation(sim.wheels[0], self.km.Wheel('b', sim.wheels[1].params, closer))
        self.assertTrue(moved.check(0, 0)['collision'])
        apart = sim.wheels[1].place.copy()
        apart[0, 3] += 10
        self.assertFalse(self.km.Simulation(sim.wheels[0], self.km.Wheel('b', sim.wheels[1].params, apart)).engaged)

    def test_incompatible_gears_are_refused(self):
        sim, r = self.sim(teeth1=18, teeth2=36, helix=20)
        a, b = sim.wheels
        same_hand = GearParams.from_dict(dict(b.params.to_dict(), hand=a.params.hand))
        with self.assertRaises(gears.GearError):
            self.km.Simulation(a, self.km.Wheel('b', same_hand, b.place))
        other_module = GearParams.from_dict(dict(b.params.to_dict(), module=3))
        with self.assertRaises(gears.GearError):
            self.km.Simulation(a, self.km.Wheel('b', other_module, b.place))
        tilted = b.place.copy()
        tilted[:3, :3] = np.array(((1, 0, 0), (0, 0, -1), (0, 1, 0)))
        with self.assertRaises(gears.GearError):
            self.km.Simulation(a, self.km.Wheel('b', b.params, tilted))


if __name__ == '__main__':
    unittest.main()
