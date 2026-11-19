"""Para kół walcowych: zazębienie dwóch kół (bez Qt i bez Open CASCADE).

Para zewnętrzna: koło 1 i koło 2 zewnętrzne, osie w odległości a. Para wewnętrzna: koło 1 (zewnętrzne, zębnik) wewnątrz
koła 2 (wieńca). Wspólne: moduł, kąt przyporu, kąt pochylenia, szerokość, luz. Kierunki skrętu: para zewnętrzna -
przeciwne, para z wieńcem - ten sam. Liczba zębów koła 2 wpisana albo z przełożenia i = z2 / z1.

Odległość osi: 0 = dobrana sama (zerowa suma korekcji albo korekcja usuwająca podcięcie zębnika przy niezmienionej
odległości); wpisana - korekcje dobrane tak, by koła zazębiały się bez luzu przy tej odległości (luz j pochodzi
z pocienienia zębów, jak w pojedynczym kole). Toczny kąt przyporu: cos αwt = a0·cos αt / a.

Warunek zazębienia bez luzu (przekrój czołowy, koła toczne):
  para zewnętrzna: s_w1 + s_w2 = p_w,  para z wieńcem: s_w1 = e_w2 (ząb zębnika = wrąb wieńca),
  s_w = d_w·(s/d + inv αt - inv αwt) - korekcja koła 2 liczona numerycznie z tego warunku.

Położenie: para zewnętrzna - koło 1 w początku układu (pierwszy ząb na +X), koło 2 na osi X w odległości a, obrócone
tak, że wrąb leży naprzeciw zęba koła 1; para z wieńcem - wieniec w początku układu (wrąb na +X), zębnik na osi X."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields

from .params import Check, GearParams, derived, inv, validate
from .profile import GearError, profile

PAIR_KINDS = ('external', 'internal')
PAIR_TITLES = {'external': 'Para zewnętrzna', 'internal': 'Koło z wieńcem'}


@dataclass
class PairParams:
    kind: str = 'external'
    teeth1: int = 20
    teeth2: int = 40
    by_ratio: bool = False          # liczba zębów koła 2 z przełożenia
    ratio: float = 2.0
    module: float = 2.0
    pressure: float = 20.0
    helix: float = 0.0              # 0 - zęby proste
    hand: str = 'right'             # kierunek skrętu koła 1; koło 2 - przeciwny (para zewnętrzna) albo ten sam (wieniec)
    width: float = 10.0
    backlash: float = 0.1           # luz pary (normalny)
    center: float = 0.0             # odległość osi, 0 = dobrana sama
    auto_shift: bool = True         # korekcja dobierana sama
    shift1: float = 0.0             # korekcja koła 1, gdy nie automatyczna (koło 2 - z warunku zazębienia)
    bore1: float = 0.0
    bore2: float = 0.0              # para zewnętrzna: otwór koła 2
    rim_diameter: float = 0.0       # wieniec: średnica zewnętrzna, 0 = dobrana sama

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        names = {f.name for f in fields(cls)}
        p = cls(**{k: v for k, v in dict(data or {}).items() if k in names})
        p.teeth1, p.teeth2 = int(round(p.teeth1)), int(round(p.teeth2))
        p.by_ratio, p.auto_shift = bool(p.by_ratio), bool(p.auto_shift)
        return p

    @property
    def internal(self):
        return self.kind == 'internal'

    @property
    def helical(self):
        return float(self.helix) > 0

    @property
    def z2(self):
        return max(1, int(round(float(self.ratio) * self.teeth1))) if self.by_ratio else int(self.teeth2)


def gear_params(pp: PairParams, which, shift):
    """Parametry pojedynczego koła pary (GearParams)."""
    helical = pp.helical
    if which == 1:
        kind, z, hand, bore, rim = ('helical_ext' if helical else 'spur_ext'), pp.teeth1, pp.hand, pp.bore1, 0.0
    else:
        internal = pp.internal
        kind = ('helical' if helical else 'spur') + ('_int' if internal else '_ext')
        z = pp.z2
        hand = pp.hand if internal else ('left' if pp.hand == 'right' else 'right')
        bore, rim = (0.0 if internal else pp.bore2), (pp.rim_diameter if internal else 0.0)
    return GearParams(kind=kind, module=pp.module, teeth=z, pressure=pp.pressure, helix=pp.helix if helical else 15.0,
                      hand=hand, width=pp.width, shift=float(shift), backlash=pp.backlash, bore=bore, rim_diameter=rim)


def _transverse(pp: PairParams):
    beta = math.radians(float(pp.helix)) if pp.helical else 0.0
    alpha_t = math.atan(math.tan(math.radians(float(pp.pressure))) / math.cos(beta))
    mt = float(pp.module) / math.cos(beta)
    return mt, alpha_t


def standard_center(pp: PairParams):
    """Odległość osi bez korekcji (a0 = mt·(z2 ± z1)/2)."""
    mt, _ = _transverse(pp)
    return mt * (pp.z2 - pp.teeth1 if pp.internal else pp.z2 + pp.teeth1) / 2


def _mesh_gap(pp, x1, x2, a):
    """Luz obwodowy na kołach tocznych przy zazębieniu (bez pocienienia na luz); 0 = zazębienie bez luzu."""
    mt, alpha_t = _transverse(pp)
    z1, z2 = pp.teeth1, pp.z2
    a0 = standard_center(pp)
    c = a0 * math.cos(alpha_t) / a
    if not -1 < c < 1:
        return None
    alpha_w = math.acos(c)
    g1 = derived(GearParams.from_dict(dict(gear_params(pp, 1, x1).to_dict(), backlash=0.0)))
    g2 = derived(GearParams.from_dict(dict(gear_params(pp, 2, x2).to_dict(), backlash=0.0)))
    rw1 = g1['db'] / 2 / math.cos(alpha_w)
    rw2 = g2['db'] / 2 / math.cos(alpha_w)
    s_w1 = 2 * rw1 * (g1['s'] / g1['d'] + inv(alpha_t) - inv(alpha_w))
    if pp.internal:
        e_w2 = 2 * rw2 * (g2['e'] / g2['d'] + inv(alpha_t) - inv(alpha_w))       # wrąb wieńca ma kształt zęba zewnętrznego
        return e_w2 - s_w1
    s_w2 = 2 * rw2 * (g2['s'] / g2['d'] + inv(alpha_t) - inv(alpha_w))
    return 2 * math.pi * rw1 / z1 - s_w1 - s_w2


def _solve_x2(pp, x1, a):
    lo, hi = -3.0, 3.0
    f = lambda x2: _mesh_gap(pp, x1, x2, a)
    flo, fhi = f(lo), f(hi)
    if flo is None or fhi is None or (flo > 0) == (fhi > 0):
        return None
    for _ in range(100):
        mid = .5 * (lo + hi)
        fm = f(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return .5 * (lo + hi)


@dataclass
class PairResult:
    params: PairParams
    gear1: GearParams
    gear2: GearParams
    z2: int
    ratio: float
    center: float            # odległość osi a
    center0: float           # odległość osi bez korekcji
    alpha_w: float           # toczny kąt przyporu czołowy (°)
    contact_ratio: float     # wskaźnik przyporu czołowy εα
    overlap_ratio: float     # wskaźnik przyporu poskokowy εβ (zęby skośne)
    clearance1: float        # luz wierzchołkowy: głowa koła 1 - stopa koła 2
    clearance2: float        # głowa koła 2 - stopa koła 1
    place1: list             # macierz 3x4 położenia koła 1
    place2: list
    checks: list

    @property
    def ok(self):
        return not any(c.level == 'error' for c in self.checks)


def _matrix(angle, x):
    c, s = math.cos(angle), math.sin(angle)
    return [[c, -s, 0.0, float(x)], [s, c, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]]


def _auto_x1(pp):
    """Korekcja zębnika usuwająca podcięcie (zaokrąglona w górę do 0,01), 0 gdy niepotrzebna."""
    x_min = derived(gear_params(pp, 1, 0.0))['x_min']
    return max(0.0, math.ceil(x_min * 100 - 1e-9) / 100)


AUTO_STEP = .05          # krok zwiększania korekcji przy automatycznym doborze (interferencja, zbyt mała różnica zębów)


def solve(pp: PairParams) -> PairResult:
    """Parametry obu kół, odległość osi, położenia i kontrola zazębienia. Korekcja automatyczna: najmniejsza, przy
    której nie ma podcięcia zębnika ani interferencji (kolejne próby co 0,05)."""
    if not pp.auto_shift:
        return _solve(pp, float(pp.shift1))
    start = _auto_x1(pp)
    if pp.internal and pp.center <= 0:
        # wieniec: większa korekcja wieńca niż zębnika - głowy wieńca wyżej nad ewolwentą zębnika, odległość osi rośnie
        tries = [(start, start + k * AUTO_STEP) for k in range(31)]
    elif pp.center > 0:
        steps = [0] + [s for k in range(1, 31) for s in (k, -k)]
        tries = [(start + k * AUTO_STEP, None) for k in steps]
    else:
        tries = [(start + k * AUTO_STEP, None) for k in range(31)]
    first = None
    for x1, x2 in tries:
        try:
            result = _solve(pp, x1, x2)
        except GearError:
            continue
        first = first or result
        if result.ok:
            return result
    return first or _solve(pp, start)


def _solve(pp: PairParams, x1, x2_wanted=None) -> PairResult:
    checks = []
    z1, z2 = pp.teeth1, pp.z2
    if pp.kind not in PAIR_KINDS:
        raise GearError('Nieznany rodzaj pary kół.')
    if pp.by_ratio and float(pp.ratio) <= 0:
        raise GearError('Przełożenie musi być dodatnie.')
    if pp.internal and z2 - z1 < 3:
        raise GearError('Wieniec musi mieć co najmniej 3 zęby więcej niż zębnik.')
    if pp.helical and not .5 <= float(pp.helix) <= 45:
        raise GearError('Kąt pochylenia: 0 (zęby proste) albo 0,5 ... 45°.')
    a0 = standard_center(pp)
    a = float(pp.center) if pp.center > 0 else None
    if a is None and x2_wanted is not None:
        x2 = x2_wanted
        a = _center_for(pp, x1, x2)
        if a is None:
            raise GearError('Nie da się dobrać odległości osi dla tych korekcji.')
    elif a is None:
        if pp.internal:
            x2 = x1                                     # zębnik i wrąb wieńca grubsze o tyle samo - odległość osi bez zmian
        else:
            x2 = -x1                                    # korekcja P-0: suma zero, odległość osi bez zmian
            if x1 > 0 and derived(gear_params(pp, 2, x2))['x_min'] > x2 + 1e-9:
                x2 = 0.0                                # koło 2 dostałoby podcięcie - suma dodatnia, odległość osi rośnie
        a = a0 if abs(x2 - (x1 if pp.internal else -x1)) < 1e-12 else (_center_for(pp, x1, x2) or a0)
    else:
        if pp.auto_shift:
            x1_free = _solve_x2(pp, 0.0, a) if not pp.internal else None
            if x1_free is not None:                     # suma korekcji dla tej odległości: podział proporcjonalny do z
                x1 = max(x1, x1_free * z2 / (z1 + z2))
        x2 = _solve_x2(pp, x1, a)
        if x2 is None:
            raise GearError(f'Przy odległości osi {a:g} mm koła nie zazębią się (za daleko albo za blisko) - '
                            f'odległość bez korekcji: {a0:.3f} mm.')
    x2 = round(x2, 6)
    g1p, g2p = gear_params(pp, 1, x1), gear_params(pp, 2, x2)
    for which, gp in ((1, g1p), (2, g2p)):
        for c in validate(gp):
            field = {'teeth': f'teeth{which}', 'shift': 'shift1' if which == 1 else 'center', 'bore': f'bore{which}',
                     'rim_diameter': 'rim_diameter'}.get(c.field, c.field)
            if c.field in ('module', 'pressure', 'width', 'backlash', 'helix', 'hand'):
                field = c.field
            checks.append(Check(c.level, field, f'Koło {which}: {c.message}'))
    if any(c.level == 'error' for c in checks):
        return _result(pp, g1p, g2p, a, a0, None, checks)
    try:
        p1, p2 = profile(g1p), profile(g2p)
    except GearError as exc:
        checks.append(Check('error', '', str(exc)))
        return _result(pp, g1p, g2p, a, a0, None, checks)
    return _result(pp, g1p, g2p, a, a0, (p1, p2), checks)


def _center_for(pp, x1, x2):
    """Odległość osi, przy której koła o korekcjach x1, x2 zazębiają się bez luzu (bisekcja)."""
    a0 = standard_center(pp)
    _, alpha_t = _transverse(pp)
    lo, hi = a0 * math.cos(alpha_t) * (1 + 1e-9), a0 * 1.5       # toczny kąt przyporu od 0 do ok. 50°
    f = lambda a: _mesh_gap(pp, x1, x2, a)
    flo, fhi = f(lo), f(hi)
    if flo is None or fhi is None or (flo > 0) == (fhi > 0):
        return None
    for _ in range(100):
        mid = .5 * (lo + hi)
        fm = f(mid)
        if fm is None:
            return None
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return .5 * (lo + hi)


def _result(pp, g1p, g2p, a, a0, profiles, checks):
    mt, alpha_t = _transverse(pp)
    z1, z2 = pp.teeth1, pp.z2
    g1, g2 = derived(g1p), derived(g2p)
    alpha_w = math.acos(max(-1.0, min(1.0, a0 * math.cos(alpha_t) / a)))
    rb1, rb2, ra1, ra2, rf1, rf2 = g1['db'] / 2, g2['db'] / 2, g1['da'] / 2, g2['da'] / 2, g1['df'] / 2, g2['df'] / 2
    pbt = g1['pb']
    sin_w = math.sin(alpha_w)
    if pp.internal:
        eps = (math.sqrt(max(ra1 ** 2 - rb1 ** 2, 0)) - math.sqrt(max(ra2 ** 2 - rb2 ** 2, 0)) + a * sin_w) / pbt
        clearance1 = rf2 - (a + ra1)                    # głowa zębnika - dno wrębu wieńca
        clearance2 = ra2 - (a + rf1)                    # głowa zęba wieńca - dno wrębu zębnika
    else:
        eps = (math.sqrt(max(ra1 ** 2 - rb1 ** 2, 0)) + math.sqrt(max(ra2 ** 2 - rb2 ** 2, 0)) - a * sin_w) / pbt
        clearance1 = a - ra1 - rf2
        clearance2 = a - ra2 - rf1
    overlap = float(pp.width) * math.sin(math.radians(float(pp.helix))) / (math.pi * float(pp.module)) if pp.helical else 0.0
    m = float(pp.module)
    ratio = z2 / z1
    if pp.by_ratio and abs(ratio - float(pp.ratio)) > .02 * float(pp.ratio):
        checks.append(Check('warning', 'ratio', f'Przełożenie {ratio:.3f} różni się od żądanego {float(pp.ratio):g} o ponad 2% '
                                                f'(liczba zębów musi być całkowita) - zmień liczbę zębów koła 1.'))
    if profiles is not None:
        p1, p2 = profiles
        # interferencja ewolwentowa: głowa jednego koła nie może zejść poniżej początku czynnej ewolwenty drugiego
        T = a * sin_w                                   # odcinek między punktami styczności linii przyporu z kołami zasadniczymi
        if pp.internal:
            reach1 = math.sqrt(max(ra2 ** 2 - rb2 ** 2, 0)) - T            # od punktu styczności zębnika
            r1_low = math.sqrt(rb1 ** 2 + reach1 ** 2) if reach1 > 0 else 0.0
            r2_out = math.sqrt(rb2 ** 2 + (math.sqrt(max(ra1 ** 2 - rb1 ** 2, 0)) + T) ** 2)
            if reach1 <= 0:
                checks.append(Check('error', 'teeth1', 'Interferencja: głowy zębów wieńca wchodzą poza punkt styczności linii przyporu '
                                                       '- zwiększ liczbę zębów zębnika albo korekcję wieńca.'))
            elif r1_low < p1.r_form - 1e-6:
                checks.append(Check('error', 'teeth1', f'Interferencja: głowa wieńca schodzi do Ø{2 * r1_low:.3f} mm, a ewolwenta zębnika '
                                                       f'zaczyna się od Ø{2 * p1.r_form:.3f} mm - zwiększ korekcję zębnika.'))
            if r2_out > p2.r_form + 1e-6:
                checks.append(Check('error', 'teeth2', f'Interferencja: głowa zębnika sięga Ø{2 * r2_out:.3f} mm w wieńcu, a jego ewolwenta '
                                                       f'kończy się na Ø{2 * p2.r_form:.3f} mm.'))
            if z2 - z1 < 10:
                checks.append(Check('warning', 'teeth2', f'Mała różnica liczby zębów (z2 - z1 = {z2 - z1}): możliwa kolizja głów zębów '
                                                         'poza linią przyporu - zalecane co najmniej 10.'))
        else:
            for which, (rb_a, ra_b, rb_b, prof) in ((1, (rb1, ra2, rb2, p1)), (2, (rb2, ra1, rb1, p2))):
                reach = T - math.sqrt(max(ra_b ** 2 - rb_b ** 2, 0))        # od punktu styczności koła which
                if reach < 0:
                    checks.append(Check('error', f'teeth{which}', f'Interferencja: głowa koła {3 - which} sięga za punkt styczności '
                                                                  f'linii przyporu koła {which} - zwiększ korekcję koła {which}.'))
                    continue
                r_low = math.sqrt(rb_a ** 2 + reach ** 2)
                if r_low < prof.r_form - 1e-6:
                    checks.append(Check('error', f'teeth{which}', f'Interferencja: głowa koła {3 - which} schodzi do Ø{2 * r_low:.3f} mm, '
                                                                  f'a ewolwenta koła {which} zaczyna się od Ø{2 * prof.r_form:.3f} mm - '
                                                                  f'zwiększ korekcję koła {which}.'))
        if eps < 1.0:
            checks.append(Check('error', 'teeth1', f'Wskaźnik przyporu εα = {eps:.2f} < 1: zęby nie przejmują pracy płynnie.'))
        elif eps < 1.2:
            checks.append(Check('warning', 'teeth1', f'Mały wskaźnik przyporu εα = {eps:.2f} (zalecane co najmniej 1,2).'))
    for which, c in ((1, clearance1), (2, clearance2)):          # luz wierzchołkowy - z samych wymiarów, zawsze
        if c <= 0:
            checks.append(Check('error', 'center', f'Głowy zębów koła {which} uderzają w dno wrębów drugiego koła '
                                                   f'(luz wierzchołkowy {c:.3f} mm) - zmień odległość osi albo korekcję.'))
        elif c < .1 * m:
            checks.append(Check('warning', 'center', f'Mały luz wierzchołkowy przy głowach koła {which}: {c:.3f} mm (zalecane 0,1·m).'))
    if pp.internal:
        place2, place1 = _matrix(math.pi / z2, 0.0), _matrix(0.0, a)           # wieniec: wrąb na +X naprzeciw zęba zębnika
    else:
        place1, place2 = _matrix(0.0, 0.0), _matrix(math.pi + math.pi / z2, a)   # koło 2: wrąb naprzeciw zęba koła 1
    return PairResult(pp, g1p, g2p, z2, ratio, a, a0, math.degrees(alpha_w), eps, overlap, clearance1, clearance2,
                      place1, place2, checks)
