"""TWIST – matematyczny silnik deformacji skręcenia (bez Open CASCADE i bez interfejsu: tylko numpy).

Skręcenie wokół osi o punkcie O i kierunku jednostkowym d. Dla punktu P:
    t      = (P - O) · d                         współrzędna wzdłuż osi
    u      = clamp((t - t0) / L, 0, 1)            położenie w zakresie deformacji [t0, t1], L = t1 - t0
    theta  = angle · f(u)                          f - rozkład skręcenia, f(0) = 0, f(1) = 1
    P'     = O + R(d, theta) · (P - O)            obrót wokół osi (wzór Rodriguesa), t się nie zmienia

Dla osi Z przez początek układu daje to dokładnie:
    x' = x·cos(theta) - y·sin(theta),  y' = x·sin(theta) + y·cos(theta),  z' = z.

Poza zakresem kąt jest stały: przed zakresem 0, za zakresem pełny kąt - na granicach ciągły, bo f(0) = 0 i f(1) = 1.
Kąt dodatni = obrót prawoskrętny wokół kierunku osi (kciuk prawej dłoni wzdłuż d); kąt ujemny - w drugą stronę;
kąty powyżej 360° są dozwolone (wiele pełnych obrotów). Odwrócenie osi (d → -d) przy tym samym zakresie odwraca
kierunek obrotu i stronę, od której narasta skręcenie.

Rozkłady f(u):
    'linear'      - u                         stały skok skręcenia na całej długości,
    'smoothstep'  - 3u² - 2u³                 łagodny początek i koniec (zerowa pochodna na granicach zakresu),
    'progressive' - u^p (p > 1, domyślnie 2)  skręcenie narasta coraz szybciej ku końcowi zakresu."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DISTRIBUTIONS = ('linear', 'smoothstep', 'progressive')
ANCHORS = ('start', 'center', 'end')   # który przekrój bryły zostaje w miejscu: początek, środek albo koniec długości
MAX_ANGLE = 36000.0          # najwyżej 100 pełnych obrotów - ochrona przed pomyłką w polu kąta
EPS = 1e-9


class TwistParamError(ValueError):
    """Nieprawidłowe parametry skręcenia (komunikat dla użytkownika po polsku)."""


def distribution(u, kind='linear', power=2.0):
    """f(u) dla u w [0, 1] (wartości spoza przedziału są przycinane)."""
    u = np.clip(np.asarray(u, float), 0.0, 1.0)
    if kind == 'linear':
        return u
    if kind == 'smoothstep':
        return u * u * (3.0 - 2.0 * u)
    if kind == 'progressive':
        return u ** float(power)
    raise TwistParamError(f'Nieznany rozkład skręcenia: {kind}.')


def distribution_slope(u, kind='linear', power=2.0):
    """f'(u) - szybkość narastania skręcenia (np. do kontroli dużych odkształceń w kolejnych etapach)."""
    u = np.clip(np.asarray(u, float), 0.0, 1.0)
    if kind == 'linear':
        return np.ones_like(u)
    if kind == 'smoothstep':
        return 6.0 * u * (1.0 - u)
    if kind == 'progressive':
        return float(power) * u ** (float(power) - 1.0)
    raise TwistParamError(f'Nieznany rozkład skręcenia: {kind}.')


@dataclass(frozen=True)
class TwistField:
    """Pole skręcenia: oś (origin, direction), kąt w stopniach, zakres [start, end] wzdłuż osi, rozkład."""
    origin: tuple
    direction: tuple
    angle: float
    start: float
    end: float
    kind: str = 'linear'
    power: float = 2.0
    offset: float = 0.0          # stopnie odejmowane od kąta wszędzie (zakotwiczenie: przekrój z kątem 0 nie musi być na początku)

    @property
    def length(self):
        return self.end - self.start

    def theta(self, t):
        """Kąt obrotu (radiany) w położeniu t wzdłuż osi."""
        u = (np.asarray(t, float) - self.start) / self.length
        return np.radians(self.angle * distribution(u, self.kind, self.power) - self.offset)

    def axial(self, points):
        """Współrzędna t punktów wzdłuż osi."""
        p = np.asarray(points, float)
        return (p - np.asarray(self.origin, float)) @ np.asarray(self.direction, float)

    def apply(self, points):
        """Punkty po skręceniu (tablica N×3 albo jeden punkt 3D) - bez zmiany oryginału."""
        p = np.asarray(points, float)
        single = p.ndim == 1
        p = p.reshape(-1, 3)
        o, d = np.asarray(self.origin, float), np.asarray(self.direction, float)
        v = p - o
        t = v @ d
        th = self.theta(t)
        c, s = np.cos(th)[:, None], np.sin(th)[:, None]
        along = np.outer(t, d)                      # składowa wzdłuż osi - bez zmian
        radial = v - along
        # Rodrigues: R·v = v·cos + (d × v)·sin + d(d·v)(1 - cos); dla składowej prostopadłej d·radial = 0
        out = o + along + radial * c + np.cross(d, radial) * s
        return out[0] if single else out

    def inverse(self):
        """Pole odwrotne (cofa skręcenie): ten sam zakres i oś, kąt przeciwny - t nie zmienia się przy obrocie."""
        return TwistField(self.origin, self.direction, -self.angle, self.start, self.end, self.kind, self.power, -self.offset)


def make_field(origin, direction, angle, start, end, kind='linear', power=2.0, offset=0.0):
    """Sprawdza parametry i tworzy TwistField (kierunek normalizowany)."""
    try:
        o = np.asarray(origin, float).reshape(3)
        d = np.asarray(direction, float).reshape(3)
        angle, start, end, power, offset = float(angle), float(start), float(end), float(power), float(offset)
    except (TypeError, ValueError):
        raise TwistParamError('Parametry skręcenia muszą być liczbami (oś: trzy współrzędne).') from None
    if not (np.isfinite(o).all() and np.isfinite(d).all() and np.isfinite([angle, start, end, power, offset]).all()):
        raise TwistParamError('Parametry skręcenia muszą być skończonymi liczbami.')
    n = float(np.linalg.norm(d))
    if n < EPS:
        raise TwistParamError('Kierunek osi skręcenia ma zerową długość.')
    if abs(angle) > MAX_ANGLE:
        raise TwistParamError(f'Kąt skręcenia może mieć najwyżej {MAX_ANGLE:g}° (100 obrotów).')
    if end - start < 1e-6:
        raise TwistParamError('Zakres skręcenia musi mieć dodatnią długość (koniec za początkiem).')
    if kind not in DISTRIBUTIONS:
        raise TwistParamError(f'Nieznany rozkład skręcenia: {kind}.')
    if kind == 'progressive' and power <= 1.0 + 1e-9:
        raise TwistParamError('Wykładnik rozkładu progresywnego musi być większy od 1.')
    return TwistField(tuple(o), tuple(d / n), angle, start, end, kind, power, offset)


def field_for_extent(origin, direction, angle, t_min, t_max, range_from=0.0, range_to=1.0, kind='linear', power=2.0, anchor='start'):
    """Pole dla bryły o zasięgu [t_min, t_max] wzdłuż osi. range_from / range_to - część długości bryły (0..1):
    0 i 1 - cała długość; np. 0.25 i 0.75 - tylko środkowa połowa (poniżej bez obrotu, powyżej pełny kąt).
    anchor - przekrój bryły, który zostaje w miejscu: 'start' (początek osi, domyślnie), 'center' (środek długości),
    'end' (koniec) - reszta obraca się względem niego (różnica kątów wzdłuż bryły bez zmian)."""
    try:
        a, b = float(range_from), float(range_to)
        t_min, t_max = float(t_min), float(t_max)
    except (TypeError, ValueError):
        raise TwistParamError('Zakres skręcenia musi być liczbą.') from None
    if not (np.isfinite([a, b, t_min, t_max]).all()):
        raise TwistParamError('Zakres skręcenia musi być skończoną liczbą.')
    if t_max - t_min < 1e-6:
        raise TwistParamError('Bryła nie ma długości wzdłuż osi skręcenia - wybierz inną oś.')
    if not (0.0 <= a < b <= 1.0):
        raise TwistParamError('Zakres skręcenia: początek i koniec między 0 a 100% długości, koniec za początkiem.')
    if anchor not in ANCHORS:
        raise TwistParamError(f'Nieznany tryb zakotwiczenia: {anchor}.')
    length = t_max - t_min
    field = make_field(origin, direction, angle, t_min + a * length, t_min + b * length, kind, power)
    at = {'start': t_min, 'center': (t_min + t_max) / 2, 'end': t_max}[anchor]
    offset = float(angle * distribution((at - field.start) / field.length, kind, power))
    return make_field(origin, direction, angle, field.start, field.end, kind, power, offset) if offset else field
