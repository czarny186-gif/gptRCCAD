"""Silnik kół zębatych (rccad.gears): wymiary pochodne i walidacja - bez Qt i bez Open CASCADE."""
import math
import os
import subprocess
import sys
import unittest

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


if __name__ == '__main__':
    unittest.main()
