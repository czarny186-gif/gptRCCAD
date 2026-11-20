"""Zarys zęba w przekroju czołowym - punkty dokładnych krzywych (numpy, bez Open CASCADE i bez Qt).

Układ: środek koła w (0, 0), oś symetrii zęba na osi +X, płaszczyzna czołowa (dla zębów skośnych: moduł czołowy mt
i kąt przyporu czołowy αt). Kąt biegunowy θ mierzony od osi zęba; górny bok ma θ > 0, dolny jest jego odbiciem.

Koło zewnętrzne - zarys obtaczany zębatką-narzędziem (ISO 53: wysokość stopy 1,25·m, zaokrąglenie wierzchołka 0,38·m):
  - bok: ewolwenta okręgu zasadniczego, θ(R) = s/(2r) + inv αt - inv αR,
  - stopa: trochoida wydłużona - obwiednia zaokrąglenia wierzchołka zębatki (liczona z zazębienia, nie przybliżana),
    styczna do ewolwenty; przy podcięciu trochoida wcina się w ewolwentę i zarys przechodzi przez ich przecięcie,
  - wierzchołek i dno wrębu: łuki okręgów głów i stóp.
Koło wewnętrzne (wieniec): bok - ewolwenta tego samego okręgu zasadniczego (wrąb ma kształt zęba koła zewnętrznego),
przejście do stopy - łuk styczny do ewolwenty i do okręgu stóp (promień 0,38·m albo mniejszy, gdy się nie mieści)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .params import Check, GearParams, derived, inv, validate

SAMPLES = 48            # punkty dokładnej krzywej przekazywane do interpolacji (ewolwenta, trochoida)


class GearError(ValueError):
    """Niepoprawne parametry albo zarys, którego nie da się zbudować."""


@dataclass
class ToothProfile:
    """Górna połowa zarysu jednego zęba (dolna to odbicie względem osi X)."""
    internal: bool
    teeth: int
    r: float            # promień podziałowy
    rb: float           # promień zasadniczy
    ra: float           # promień głów
    rf: float           # promień stóp
    flank: np.ndarray   # ewolwenta (N, 2): od połączenia ze stopą do głowy
    fillet: np.ndarray  # przejście stopy (N, 2): od okręgu stóp do połączenia z ewolwentą
    fillet_kind: str    # 'trochoid' (koło zewnętrzne) albo 'arc' (koło wewnętrzne: 3 punkty łuku)
    fillet_center: tuple | None   # środek łuku przejścia (koło wewnętrzne)
    root_angle: float   # θ początku przejścia na okręgu stóp; dno wrębu do kąta 2π/z - root_angle następnego zęba
    tip_angle: float    # θ końca ewolwenty na okręgu głów (połowa grubości wierzchołka)
    r_form: float       # promień połączenia ewolwenty z przejściem stopy (początek czynnej ewolwenty)
    rho: float          # użyty promień zaokrąglenia (zębatki albo łuku)
    undercut: bool      # stopa podcięta (trochoida wcina się w ewolwentę)
    fillets_meet: bool  # przejścia sąsiednich zębów spotykają się na środku wrębu (brak łuku dna)
    flank_tangents: np.ndarray = None    # (2, 2) jednostkowe styczne ewolwenty na początku i końcu (kierunek kolejności punktów)
    fillet_tangents: np.ndarray = None   # (2, 2) styczne przejścia stopy (trochoida); łuk - None

    @staticmethod
    def mirrored(points):
        """Odbicie względem osi zęba (dolny bok), w tej samej kolejności punktów."""
        return np.asarray(points) * (1, -1)


def _xy(R, theta):
    return np.column_stack((R * np.cos(theta), R * np.sin(theta)))


def _bisect(f, a, b, n=80):
    fa = f(a)
    for _ in range(n):
        c = .5 * (a + b)
        fc = f(c)
        if (fc > 0) == (fa > 0):
            a, fa = c, fc
        else:
            b = c
    return .5 * (a + b)


def involute_angle(rb, R):
    """inv(αR) dla promienia R ≥ rb."""
    return inv(math.acos(min(1.0, rb / R)))


_PROFILES = {}           # pamięć zarysów: zarys zależy tylko od uzębienia (nie od szerokości, otworu, piasty)


def tooth_key(params: GearParams):
    """Klucz uzębienia - parametry, od których zależy zarys zęba w przekroju czołowym."""
    return (params.kind, float(params.module), int(params.teeth), float(params.pressure),
            float(params.helix) if params.helical else 0.0, float(params.shift), float(params.backlash),
            float(params.rim_diameter) if params.internal else 0.0)


def profile(params: GearParams) -> ToothProfile:
    """Zarys zęba; GearError przy niepoprawnych parametrach. Wynik zapamiętany dla tego samego uzębienia (zmiana szerokości,
    otworu, piasty albo kolejne próby korekcji w parze kół nie liczą zarysu od nowa); zarys traktować jako tylko do odczytu."""
    errors = [c for c in validate(params) if c.level == 'error']     # zawsze - także otwór, piasta, rowek
    if errors:
        raise GearError(errors[0].message)
    key = tooth_key(params)
    hit = _PROFILES.get(key)
    if hit is not None:
        return hit
    prof = _internal(params) if params.internal else _external(params)
    if len(_PROFILES) >= 256:
        _PROFILES.pop(next(iter(_PROFILES)))
    _PROFILES[key] = prof
    return prof


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _curve_tangent(point_of, t, h):
    """Jednostkowa styczna krzywej danej wzorem (różnica centralna)."""
    return _unit(np.asarray(point_of(t + h)) - np.asarray(point_of(t - h)))


def _flank_tangents(rb, theta_of, r0, r1):
    """Styczne ewolwenty na końcach (w parametrze rozwinięcia t, R = rb·√(1+t²))."""
    def at(t):
        R = rb * math.sqrt(1 + t * t)
        th = theta_of(R)
        return (R * math.cos(th), R * math.sin(th))
    t0 = math.sqrt(max(r0 * r0 / (rb * rb) - 1, 0.0))
    t1 = math.sqrt(max(r1 * r1 / (rb * rb) - 1, 0.0))
    h = 1e-6 * max(t0, t1, 1e-3)
    sign = 1.0 if t1 >= t0 else -1.0   # styczne w kierunku kolejności punktów (koło wewnętrzne: od stopy do głowy = R maleje)
    t0, t1 = max(t0, h), max(t1, h)    # na samym okręgu zasadniczym ewolwenta ma ostrze - styczna tuż nad nim
    return sign * np.array((_curve_tangent(at, t0, h), _curve_tangent(at, t1, h)))


def _flank_points(rb, theta_of, r0, r1, n=SAMPLES):
    """Ewolwenta od promienia r0 do r1 - punkty równomiernie w kącie rozwinięcia (gęściej przy okręgu zasadniczym)."""
    t0 = math.sqrt(max(r0 * r0 / (rb * rb) - 1, 0.0))
    t1 = math.sqrt(max(r1 * r1 / (rb * rb) - 1, 0.0))
    t = np.linspace(t0, t1, n)
    R = rb * np.sqrt(1 + t * t)
    R[0], R[-1] = r0, r1
    return _xy(R, np.array([theta_of(x) for x in R]))


def _external(p: GearParams) -> ToothProfile:
    g = derived(p)
    m, z = float(p.module), int(p.teeth)
    alpha = math.radians(g['alpha_t'])
    r, rb, ra, rf = g['d'] / 2, g['db'] / 2, g['da'] / 2, g['df'] / 2
    s_t = g['s']
    half_pitch = math.pi / z

    def theta_inv(R):
        return s_t / (2 * r) + inv(alpha) - involute_angle(rb, R)

    rho = g['rho']
    v_tip = (float(p.shift) - 1.25) * m             # wierzchołek zębatki pod linią toczną (dno wrębu koła)
    v_c = v_tip + rho                                # środek zaokrąglenia wierzchołka zębatki (układ zębatki: u wzdłuż, v na zewnątrz)
    u_c = s_t / 2 - v_c * math.tan(alpha) + rho / math.cos(alpha)

    def fillet_point(phi):
        """Punkt obwiedni zaokrąglenia zębatki przy obrocie koła o φ (zazębienie: normalna przez biegun toczenia)."""
        iu, iv = r * phi, 0.0
        du, dv = u_c - iu, v_c - iv
        n = math.hypot(du, dv)
        qu, qv = u_c + rho * du / n, v_c + rho * dv / n
        a, b = qu - r * phi, r + qv
        x, y = a * math.cos(phi) + b * math.sin(phi), -a * math.sin(phi) + b * math.cos(phi)
        return math.hypot(x, y), math.atan2(x, y)

    phi0 = u_c / r                                   # wierzchołek zębatki dokładnie pod biegunem: dno wrębu
    phi1 = (u_c - v_c / math.tan(alpha)) / r if rho > 0 else phi0      # koniec zaokrąglenia: początek prostego boku
    if phi1 <= phi0 + 1e-15:                         # zębatka bez zaokrąglenia: przejście to sam narożnik
        phi1 = phi0 + 1e-9
    phis = np.linspace(phi0, phi1, 400)
    pts = np.array([fillet_point(f) for f in phis])

    # początek: przejścia sąsiednich zębów nie mogą przekroczyć środka wrębu
    start, fillets_meet = phi0, False
    if pts[0, 1] > half_pitch:
        fillets_meet = True
        k = int(np.argmax(pts[:, 1] <= half_pitch))
        if pts[k, 1] > half_pitch:
            raise GearError('Wręby tak wąskie, że przejścia stóp sąsiednich zębów nachodzą na siebie.')
        start = _bisect(lambda f: fillet_point(f)[1] - half_pitch, phis[k - 1], phis[k])

    # koniec: styczne przejście w ewolwentę albo przecięcie z nią (podcięcie)
    # Przy podcięciu trochoida nad okręgiem zasadniczym leży wewnątrz zęba (θ mniejsze niż ewolwenty), potem wychodzi
    # przez ewolwentę - zarys (mniejsze θ) przechodzi z trochoidy na ewolwentę w tym przecięciu (zmiana znaku - na +).
    delta = np.array([t - theta_inv(R) if R >= rb else np.nan for R, t in pts])
    inside = np.nan_to_num(delta, nan=1.0) < -1e-9
    cross = np.nonzero(inside[:-1] & ~inside[1:])[0]
    end, undercut = phi1, False
    if inside.any():
        if not len(cross):
            raise GearError('Nie da się połączyć stopy z ewolwentą - sprawdź liczbę zębów i korekcję zarysu.')
        k = int(cross[-1])
        undercut = True

        def gap(f):
            R, t = fillet_point(f)
            return t - theta_inv(R) if R >= rb else -1.0
        end = _bisect(gap, phis[k], phis[k + 1])
    elif pts[-1, 0] < rb - 1e-9:
        raise GearError('Stopa zęba kończy się pod okręgiem zasadniczym - za mało zębów przy tej korekcji.')
    else:
        undercut = bool(g['undercut'])
    if end <= start:
        raise GearError('Przejście stopy zęba zanika - zmień korekcję zarysu albo liczbę zębów.')

    fil = np.array([fillet_point(f) for f in np.linspace(start, end, SAMPLES)])
    fil_xy = lambda f: (lambda R, t: (R * math.cos(t), R * math.sin(t)))(*fillet_point(f))
    h = 1e-7 * max(end - start, 1e-9)
    fillet_tangents = np.array((_curve_tangent(fil_xy, start + h, h), _curve_tangent(fil_xy, end - h, h)))
    r_form = float(fil[-1, 0])
    if not undercut:                                  # styczne przejście: dokładnie na ewolwencie
        fil[-1, 1] = theta_inv(r_form)
    tip = theta_inv(ra)
    if tip <= 0:
        raise GearError('Ząb zaostrzony: ewolwenty boków przecinają się pod okręgiem głów.')
    if r_form >= ra:
        raise GearError('Przejście stopy sięga głowy zęba - brak czynnej ewolwenty.')
    flank = _flank_points(rb, theta_inv, r_form, ra)
    flank[0] = _xy(np.array([r_form]), np.array([fil[-1, 1]]))[0]
    flank_tangents = _flank_tangents(rb, theta_inv, r_form, ra)
    if not undercut:                   # styczne przejście (G1): koniec trochoidy ma kierunek początku ewolwenty
        fillet_tangents[1] = flank_tangents[0]
    return ToothProfile(False, z, r, rb, ra, rf, flank, _xy(fil[:, 0], fil[:, 1]), 'trochoid', None,
                        float(fil[0, 1]), tip, r_form, rho, undercut, fillets_meet, flank_tangents, fillet_tangents)


def _internal(p: GearParams) -> ToothProfile:
    g = derived(p)
    m, z = float(p.module), int(p.teeth)
    alpha = math.radians(g['alpha_t'])
    r, rb, ra, rf = g['d'] / 2, g['db'] / 2, g['da'] / 2, g['df'] / 2
    half_pitch = math.pi / z
    e_t = g['e']                                     # wrąb koła wewnętrznego (kształt zęba koła zewnętrznego)

    def theta_tooth(R):                              # połowa grubości zęba wewnętrznego
        return half_pitch - (e_t / (2 * r) + inv(alpha) - involute_angle(rb, R))

    tip = theta_tooth(ra)
    if tip <= 0:
        raise GearError('Ząb koła wewnętrznego zaostrzony - zmniejsz korekcję zarysu albo luz.')
    if theta_tooth(rf) >= half_pitch:
        raise GearError('Wrąb koła wewnętrznego zamyka się przed okręgiem stóp - zmień korekcję zarysu.')

    def flank_xy(R):
        t = theta_tooth(R)
        return np.array((R * math.cos(t), R * math.sin(t)))

    def nearest(center, lo, hi):
        """Najbliższy punkt boku (ewolwenty) do punktu: złoty podział w promieniu (zwykła arytmetyka - wywoływane tysiące razy)."""
        cx, cy = float(center[0]), float(center[1])

        def f(R):
            t = theta_tooth(R)
            return math.hypot(R * math.cos(t) - cx, R * math.sin(t) - cy)
        a, b = lo, hi
        k = (math.sqrt(5) - 1) / 2
        c, d = b - k * (b - a), a + k * (b - a)
        fc, fd = f(c), f(d)
        for _ in range(64):                        # 0,618^64 - poniżej dokładności liczb zmiennoprzecinkowych
            if fc < fd:
                b, d, fd = d, c, fc
                c = b - k * (b - a)
                fc = f(c)
            else:
                a, c, fc = c, d, fd
                d = a + k * (b - a)
                fd = f(d)
        R = .5 * (a + b)
        return R, f(R)

    def fit(rho):
        """Środek łuku przejścia o promieniu rho: styczny do okręgu stóp (od środka) i do boku. None - nie mieści się."""
        rc = rf - rho

        def gap(gamma):
            c = np.array((rc * math.cos(gamma), rc * math.sin(gamma)))
            return nearest(c, max(ra, rb), rf)[1] - rho
        if rc <= max(ra, rb):
            return None
        lo, hi = theta_tooth(rc), half_pitch           # środek na boku (odległość 0) ... na środku wrębu
        if gap(hi) < 0:                                # łuk nie mieści się we wrębie - mniejszy promień
            return None
        return _bisect(gap, lo, hi, 56)

    rho = .38 * m
    gamma = fit(rho)
    while gamma is None and rho > 1e-3 * m:
        rho *= .8
        gamma = fit(rho)
    if gamma is None:
        raise GearError('Nie mieści się przejście stopy zęba koła wewnętrznego.')
    rc = rf - rho
    center = np.array((rc * math.cos(gamma), rc * math.sin(gamma)))
    r_form, _ = nearest(center, max(ra, rb), rf)
    a = flank_xy(r_form)
    b = np.array((rf * math.cos(gamma), rf * math.sin(gamma)))
    va, vb = (a - center) / np.linalg.norm(a - center), (b - center) / np.linalg.norm(b - center)
    mid = center + rho * (va + vb) / np.linalg.norm(va + vb)
    flank = _flank_points(rb, theta_tooth, r_form, ra)
    flank[0] = a
    fillets_meet = gamma >= half_pitch - 1e-12
    return ToothProfile(True, z, r, rb, ra, rf, flank, np.array((b, mid, a)), 'arc', (float(center[0]), float(center[1])),
                        float(gamma), tip, float(r_form), rho, False, bool(fillets_meet), _flank_tangents(rb, theta_tooth, r_form, ra))


def outline_points(params: GearParams, samples=SAMPLES):
    """Gęsty zamknięty zarys całego koła (punkty) - do kontroli i pola przekroju; kolejność przeciwna do wskazówek zegara."""
    prof = profile(params)
    z = prof.teeth

    def pick(points):            # mniej punktów niż w zarysie (szybki podgląd): co któryś, z oboma końcami
        if samples >= len(points):
            return points
        return points[np.unique(np.round(np.linspace(0, len(points) - 1, max(samples, 2))).astype(int))]
    flank = pick(prof.flank)
    fillet = prof.fillet if prof.fillet_kind == 'arc' else pick(prof.fillet)
    lower_flank, lower_fil = prof.mirrored(flank), prof.mirrored(fillet)
    if prof.fillet_kind == 'arc':
        cx, cy = prof.fillet_center
        def arc(pts, center):
            a0 = math.atan2(pts[0][1] - center[1], pts[0][0] - center[0])
            a1 = math.atan2(pts[-1][1] - center[1], pts[-1][0] - center[0])
            d = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
            a = a0 + d * np.linspace(0, 1, samples)
            return np.column_stack((center[0] + prof.rho * np.cos(a), center[1] + prof.rho * np.sin(a)))
        up_fil = arc(prof.fillet, (cx, cy))
        low_fil = arc(lower_fil, (cx, -cy))
    else:
        up_fil, low_fil = fillet, lower_fil
    tip = _xy(np.full(samples, prof.ra), np.linspace(-prof.tip_angle, prof.tip_angle, samples))
    tooth = np.vstack((low_fil, lower_flank[1:], tip[1:], flank[::-1][1:], up_fil[::-1][1:]))
    # tooth: od dolnego początku przejścia (dno wrębu) przez głowę do górnego początku przejścia
    gap = 2 * math.pi / z - 2 * prof.root_angle
    root = _xy(np.full(samples, prof.rf), prof.root_angle + gap * np.linspace(0, 1, samples))
    one = np.vstack((tooth, root[1:-1])) if gap > 1e-12 else tooth
    out = []
    for i in range(z):
        c, s = math.cos(2 * math.pi * i / z), math.sin(2 * math.pi * i / z)
        out.append(one @ np.array(((c, s), (-s, c))))
    return np.vstack(out)


def check(params: GearParams):
    """Pełne sprawdzenie: walidacja liczbowa i próba zbudowania zarysu. Zwraca (lista Check, ToothProfile albo None)."""
    checks = validate(params)
    if any(c.level == 'error' for c in checks):
        return checks, None
    try:
        return checks, profile(params)
    except GearError as exc:
        return checks + [Check('error', '', str(exc))], None


def polygon_area(points):
    x, y = points[:, 0], points[:, 1]
    return .5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
