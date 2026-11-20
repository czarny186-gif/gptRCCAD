"""Kinematyka pary kół walcowych - symulacja obrotu i kontrola kolizji (bez Qt i bez Open CASCADE).

Dwa koła z parametrami (GearParams) i położeniem (macierz 3x4 względem koła z generatora - meta['gear_place']).
Osie muszą być równoległe. Koła obracają się wokół własnych osi (wspólny kierunek osi = oś koła 1), więc odległość
osi się nie zmienia; kąty zgodnie z przełożeniem: para zewnętrzna - przeciwnie, koło z wieńcem - w tę samą stronę:
    θ_napędzane = ∓ θ_napędzające · z_napędzające / z_napędzane.
Faza zębów: położenie startowe to położenie z modelu (para z generatora - ząb naprzeciw wrębu), dalej obrót dokładnie
w przełożeniu - faza się nie rozjeżdża.

Kolizja: przekroje czołowe kół (dokładny zarys z profile.outline_points, wieniec jako pierścień) w płaszczyźnie koła 1,
na dole i u góry wspólnej szerokości (zęby skośne - przekroje obrócone o skręt); wspólne pole > 0 - kolizja; najmniejszy
odstęp zarysów w strefie zazębienia (przekrój czołowy) - luz."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .params import GearParams, derived
from .profile import GearError, outline_points

SAMPLES = 24             # punkty na krzywą zarysu w przekroju do kontroli kolizji
OVERLAP_TOL = 1e-6       # mm² - wspólne pole przekrojów uznane za kolizję


def _twist(p: GearParams):
    if not p.helical:
        return 0.0
    angle = 2 * float(p.width) * math.tan(math.radians(p.beta)) / derived(p)['d']
    return angle if p.hand == 'right' else -angle


def _m4(place):
    m = np.eye(4)
    m[:3, :4] = np.asarray(place, float)[:3, :4] if place is not None else np.eye(4)[:3, :4]
    return m


def _rot2(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array(((c, -s), (s, c)))


def rotation_matrix(axis, center, angle):
    """Macierz 4x4 obrotu o kąt (rad) wokół osi przez punkt."""
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    x, y, z = a
    c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    R = np.array(((t * x * x + c, t * x * y - s * z, t * x * z + s * y),
                  (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
                  (t * x * z - s * y, t * y * z + s * x, t * z * z + c)))
    m = np.eye(4)
    m[:3, :3] = R
    m[:3, 3] = np.asarray(center, float) - R @ np.asarray(center, float)
    return m


@dataclass
class Wheel:
    id: str
    params: GearParams
    place: np.ndarray        # 4x4 położenie względem koła z generatora


class Simulation:
    """Para kół do symulacji. Wyjątek GearError, gdy kół nie da się zazębić (osie, moduł, kąty, kierunki)."""

    def __init__(self, first: Wheel, second: Wheel):
        if first.params.internal and second.params.internal:
            raise GearError('Dwa koła wewnętrzne nie mogą ze sobą współpracować.')
        if first.params.internal:                       # koło 1 - zewnętrzne (zębnik), koło 2 - zewnętrzne albo wieniec
            first, second = second, first
        self.wheels = (first, second)
        p1, p2 = first.params, second.params
        self.internal = p2.internal
        if abs(p1.module - p2.module) > 1e-9 or abs(p1.pressure - p2.pressure) > 1e-9:
            raise GearError('Koła mają różny moduł albo kąt przyporu - nie zazębią się.')
        if p1.helical != p2.helical or (p1.helical and abs(p1.helix - p2.helix) > 1e-9):
            raise GearError('Koła mają różny kąt pochylenia zębów - nie zazębią się.')
        if p1.helical and (p1.hand == p2.hand) != self.internal:
            raise GearError('Złe kierunki skrętu: para zewnętrzna - przeciwne, koło z wieńcem - ten sam.')
        self.P1 = first.place
        self.axis = self.P1[:3, 2] / np.linalg.norm(self.P1[:3, 2])
        Q = np.linalg.inv(self.P1) @ second.place           # koło 2 w układzie koła 1
        if abs(abs(Q[2, 2]) - 1) > 1e-6:
            raise GearError('Osie kół nie są równoległe - symulacja przekładni walcowej niemożliwa.')
        self.Q = (np.eye(4), Q)
        self.sign = (1.0, float(np.sign(Q[2, 2])))          # oś koła 2 zgodna (+1) albo odwrócona (-1) względem koła 1
        self.centers2d = (np.zeros(2), Q[:2, 3].copy())
        self.center = float(np.linalg.norm(self.centers2d[1]))
        # wspólny zakres osiowy (w układzie koła 1)
        lo2, hi2 = sorted((Q[2, 3], Q[2, 3] + self.sign[1] * p2.width))
        self.z_range = (max(0.0, lo2), min(p1.width, hi2))
        g1, g2 = derived(p1), derived(p2)
        self.ratio = p2.teeth / p1.teeth
        ra1, ra2 = g1['da'] / 2, g2['da'] / 2
        if self.internal:
            self.engaged = self.center + ra1 > ra2 and self.center < g2['df'] / 2
            rw1 = self.center * p1.teeth / max(p2.teeth - p1.teeth, 1)
        else:
            self.engaged = self.center < ra1 + ra2
            rw1 = self.center * p1.teeth / (p1.teeth + p2.teeth)
        direction = self.centers2d[1] / max(self.center, 1e-12)
        self.pitch_point = (-direction if self.internal else direction) * rw1 if self.center > 1e-9 else np.array((rw1, 0.0))
        self.zone = 3.0 * float(p1.module)
        self._sections = None

    # ---------- kąty i macierze ----------
    def angles(self, driver, theta):
        """Kąty obrotu kół (rad, wokół wspólnej osi koła 1) przy obrocie koła napędzającego (0 - koło 1, 1 - koło 2) o theta."""
        z = (self.wheels[0].params.teeth, self.wheels[1].params.teeth)
        k = z[driver] / z[1 - driver] * (1.0 if self.internal else -1.0)
        out = [0.0, 0.0]
        out[driver], out[1 - driver] = theta, theta * k
        return tuple(out)

    def matrices(self, theta1, theta2):
        """{id: macierz 4x4} obrotu brył kół wokół ich osi (dla widoku - bez przebudowy geometrii)."""
        result = {}
        for wheel, angle in zip(self.wheels, (theta1, theta2)):
            result[wheel.id] = rotation_matrix(self.axis, wheel.place[:3, 3], angle)
        return result

    def speeds(self, driver, rpm):
        """(prędkość wyjściowa obr/min, ten sam kierunek obrotu?) dla prędkości wejściowej koła napędzającego."""
        z = (self.wheels[0].params.teeth, self.wheels[1].params.teeth)
        return rpm * z[driver] / z[1 - driver], self.internal

    # ---------- kontrola kolizji ----------
    def _section_polys(self):
        """Przekroje czołowe obu kół (punkty w układzie własnym koła) na wysokościach kontroli (w układzie koła 1)."""
        if self._sections is not None:
            return self._sections
        lo, hi = self.z_range
        if hi < lo - 1e-9:
            heights = []                                # koła nie zachodzą na siebie wzdłuż osi
        elif not self.wheels[0].params.helical or hi - lo < 1e-9:
            heights = [.5 * (lo + hi)]                  # zęby proste: jeden przekrój wystarczy
        else:
            heights = [lo + 1e-6 * (hi - lo), hi - 1e-6 * (hi - lo)]   # skośne: dół i góra (skręt)
        sections = []
        for h in heights:
            per_wheel = []
            for k, wheel in enumerate(self.wheels):
                p = wheel.params
                Q = self.Q[k]
                zk = (h - Q[2, 3]) / self.sign[k]
                outline = outline_points(p, SAMPLES) @ _rot2(_twist(p) * zk / p.width).T
                rings = [outline]
                if p.internal:
                    a = np.linspace(0, 2 * math.pi, 256, endpoint=False)
                    R = derived(p)['rim'] / 2
                    rings = [np.column_stack((R * np.cos(a), R * np.sin(a))), outline]
                per_wheel.append(rings)
            sections.append(per_wheel)
        self._sections = sections
        return sections

    def _placed(self, k, theta, points):
        """Punkty przekroju koła k w płaszczyźnie koła 1 po obrocie o theta (wokół jego osi)."""
        Q = self.Q[k]
        local = points @ Q[:2, :2].T + Q[:2, 3]
        c = self.centers2d[k]
        return (local - c) @ _rot2(theta).T + c

    def check(self, theta1, theta2, with_gap=True):
        """{'overlap': wspólne pole przekrojów (mm²), 'gap': najmniejszy odstęp zarysów w strefie zazębienia (mm, przekrój
        czołowy; None - zęby poza zasięgiem albo with_gap=False), 'collision': bool}. Kolizja (wspólne pole) - zawsze;
        odstęp (droższy) - na życzenie."""
        import manifold3d as mf
        overlap, gap = 0.0, None
        for per_wheel in self._section_polys():
            placed = [[self._placed(k, th, ring) for ring in per_wheel[k]] for k, th in ((0, theta1), (1, theta2))]
            a = mf.CrossSection(placed[0], mf.FillRule.EvenOdd)
            b = mf.CrossSection(placed[1], mf.FillRule.EvenOdd)
            overlap = max(overlap, (a ^ b).area())
            g = self._gap(placed[0][-1], placed[1][-1]) if with_gap else None
            if g is not None:
                gap = g if gap is None else min(gap, g)
        return dict(overlap=overlap, gap=gap, collision=overlap > OVERLAP_TOL)

    def _gap(self, A, B):
        """Najmniejsza odległość punktów jednego zarysu od odcinków drugiego (oba kierunki) w strefie zazębienia."""
        best = None
        for P, S in ((A, B), (B, A)):
            near_p = P[np.linalg.norm(P - self.pitch_point, axis=1) < self.zone]
            idx = np.nonzero(np.linalg.norm(S - self.pitch_point, axis=1) < self.zone)[0]
            if not len(near_p) or not len(idx):
                continue
            s0, s1 = S[idx], S[(idx + 1) % len(S)]
            d = s1 - s0
            length2 = np.maximum((d * d).sum(1), 1e-30)
            t = np.clip(((near_p[:, None, :] - s0[None]) * d[None]).sum(2) / length2[None], 0, 1)
            closest = s0[None] + t[..., None] * d[None]
            dist = float(np.sqrt(((near_p[:, None, :] - closest) ** 2).sum(2)).min())
            best = dist if best is None else min(best, dist)
        return best

    def sweep(self, driver=0, samples=24):
        """Kontrola na całej podziałce zęba koła napędzającego: (największe wspólne pole, najmniejszy odstęp)."""
        z = self.wheels[driver].params.teeth
        worst_overlap, worst_gap = 0.0, None
        for theta in np.linspace(0, 2 * math.pi / z, samples, endpoint=False):
            result = self.check(*self.angles(driver, float(theta)))
            worst_overlap = max(worst_overlap, result['overlap'])
            if result['gap'] is not None:
                worst_gap = result['gap'] if worst_gap is None else min(worst_gap, result['gap'])
        return worst_overlap, worst_gap
