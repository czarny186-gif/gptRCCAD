"""Tekstury geometryczne - generatory 16 wzorów w dziedzinie powierzchni (współrzędne 2D w mm).

Każdy generator zwraca listę elementów (El) pokrywających prostokąt lo-hi (obszar jest przycinany później, wspólnym
silnikiem). Wzór liczy się w układzie wzoru (obrót, odbicie, skala niezależna w dwóch kierunkach, przesunięcie), a elementy
wracają do dziedziny. Rodzaje elementów: 'poly' (wielokąt z otworami, wyciągany z opcjonalnym zwężeniem), 'bar' (listwa o profilu
wzdłuż odcinka), 'dome' (bryła obrotowa), 'solid' (własna bryła)."""
from __future__ import annotations

import math

import numpy as np

from . import kernel

PATTERNS = ('knurl_cross', 'knurl_straight', 'knurl_spiral', 'honeycomb', 'dots', 'pyramids', 'waves', 'voronoi', 'checker', 'herringbone',
            'rings', 'scales', 'weave', 'hammered', 'triangles', 'custom', 'image')
PATTERN_LABELS = {'knurl_cross': 'Radełkowanie krzyżowe (diamenty)', 'knurl_straight': 'Radełkowanie proste', 'knurl_spiral': 'Radełkowanie spiralne',
                  'honeycomb': 'Plaster miodu', 'dots': 'Punkty i półkule', 'pyramids': 'Piramidy', 'waves': 'Fale', 'voronoi': 'Voronoi',
                  'checker': 'Blacha ryflowana', 'herringbone': 'Jodełka', 'rings': 'Pierścienie koncentryczne', 'scales': 'Łuski',
                  'weave': 'Plecionka', 'hammered': 'Powierzchnia młotkowana', 'triangles': 'Siatka trójkątna', 'custom': 'Własny wzór użytkownika', 'image': 'Mapa wysokości z obrazu'}
MODES = ('convex', 'concave', 'mixed', 'separate', 'preview')
MODE_LABELS = {'convex': 'Wypukła (dodaje materiał)', 'concave': 'Wklęsła (odejmuje materiał)', 'mixed': 'Mieszana (wypustki i zagłębienia)',
               'separate': 'Oddzielne bryły', 'preview': 'Podgląd graficzny (bez zmiany modelu)'}


class El:
    """Element tekstury w dziedzinie: kind poly / bar / dome / solid; sign +1 wypustka, -1 zagłębienie; hs - mnożnik wysokości."""
    __slots__ = ('kind', 'c', 'poly', 'holes', 'p0', 'p1', 'w', 'hs', 'hd', 'sign', 'k', 'tilt', 'prof', 'shape', 'd', 'ang', 'idx', 'extra')

    def __init__(self, kind, c, **kw):
        self.kind = kind
        self.c = np.asarray(c, float)
        self.poly = kw.get('poly')
        self.holes = kw.get('holes') or []
        self.p0 = kw.get('p0')
        self.p1 = kw.get('p1')
        self.w = kw.get('w', 0.0)
        self.hs = kw.get('hs', 1.0)
        self.hd = kw.get('hd', None)
        self.sign = kw.get('sign', 1)
        self.k = kw.get('k', 1.0)
        self.tilt = kw.get('tilt', (0.0, 0.0))
        self.prof = kw.get('prof', 'rect')
        self.shape = kw.get('shape', 'cap')
        self.d = kw.get('d', 0.0)
        self.ang = kw.get('ang', 0.0)
        self.idx = kw.get('idx', 0)
        self.extra = kw.get('extra')

    def moved(self, f):
        """Kopia elementu z punktami przekształconymi funkcją f(Nx2) → Nx2 (do mapowania wzoru z układu wzoru do dziedziny)."""
        e = El(self.kind, f(self.c[None])[0], poly=None if self.poly is None else f(self.poly), holes=[f(h) for h in self.holes],
               p0=None if self.p0 is None else f(np.asarray(self.p0)[None])[0], p1=None if self.p1 is None else f(np.asarray(self.p1)[None])[0],
               w=self.w, hs=self.hs, hd=self.hd, sign=self.sign, k=self.k, tilt=self.tilt, prof=self.prof, shape=self.shape, d=self.d, ang=self.ang,
               idx=self.idx, extra=self.extra)
        return e

    def extent(self):
        if self.kind == 'poly':
            return float(np.max(np.linalg.norm(self.poly - self.c, axis=1)))
        if self.kind == 'bar':
            return float(np.linalg.norm(np.asarray(self.p1) - np.asarray(self.p0))) / 2 + self.w / 2
        return self.d / 2


DEFAULTS = dict(
    pattern='knurl_cross', mode='convex', size=4.0, px=0.0, py=0.0, width=1.0, wall=.6, height=.6, depth=.6, angle=0.0, ox=0.0, oy=0.0,
    sx=1.0, sy=1.0, margin=1.0, margin_holes=1.0, radius=0.0, draft=0.0, nx=0, ny=0, density=1.0, randomness=0.0, seed=1,
    reverse=False, mirror=False, fit='exact', boundary='clip', origin=None,
    # radełkowanie
    groove_angle=60.0, tip='sharp', profile='rect', trap=.4, hand='right', helix=45.0, starts=1, groove=.8,
    # plaster miodu, siatka trójkątna, Voronoi
    fill='solid', row_shift=50.0, tri_kind='equilateral', tri_ratio=1.3, alternate=True, cells=0, irregular=.5, corner=0.0,
    # punkty, piramidy
    dot_shape='hemisphere', dot_layout='rect', sides=4, trunc=0.0, edge_round=0.0,
    # fale
    wave_type='sine', amp=.5, wavelength=6.0, wave_dir=0.0, wave2=False, wave2_dir=90.0, wave2_amp=.5, wave2_len=6.0,
    # blacha ryflowana, jodełka
    bump_n=1, bump_shape='oval', bump_len=8.0, bump_w=2.4, bump_gap=1.2, bump_angle=45.0, arm_angle=45.0, arm_len=6.0, arm_w=1.4,
    # pierścienie
    ring_r0=2.0, ring_gap=1.5, ring_w=1.0, ring_a0=0.0, ring_a1=360.0, ring_cx=0.0, ring_cy=0.0, ring_n=0,
    # łuski
    scale_shape='round', overlap=.3, tilt=20.0,
    # plecionka
    weave_kind='straight', weave_gap=.4, strip=2.0,
    # młotkowana
    ham_min=2.0, ham_max=4.0, ham_dmin=.2, ham_dmax=.6,
    # własny wzór
    custom_src='sketch', custom_loops=None, custom_body=None, c_layout='rect', c_rot=0.0, c_scale=1.0, c_count=6, c_arms=6,
    # tryby dokładności i zabezpieczenia
    accuracy='exact', tol=.05, min_wall=0.8, protect_wall=True, mixed_rule='alternate', mixed_pct=50.0,
    gradients=[], image=None,
)

# (klucz, tytuł, min, max, miejsca, krok, jednostka) - pola liczbowe; GRUPY mówią, który wzór ich używa
FIELDS = (
    ('size', 'Wielkość elementu', .2, 500, 2, .25, ' mm'), ('px', 'Rozstaw poziomy (0 = z wielkości)', 0, 500, 2, .25, ' mm'),
    ('py', 'Rozstaw pionowy (0 = jak poziomy)', 0, 500, 2, .25, ' mm'), ('width', 'Szerokość elementów', .05, 200, 2, .1, ' mm'),
    ('wall', 'Grubość ścianek', .05, 50, 2, .1, ' mm'), ('height', 'Wysokość wypustek', .02, 100, 2, .1, ' mm'),
    ('depth', 'Głębokość zagłębień', .02, 100, 2, .1, ' mm'), ('angle', 'Kąt obrotu wzoru', -360, 360, 1, 5, ' °'),
    ('ox', 'Przesunięcie poziome', -1e4, 1e4, 2, .5, ' mm'), ('oy', 'Przesunięcie pionowe', -1e4, 1e4, 2, .5, ' mm'),
    ('sx', 'Skala pozioma', .05, 20, 2, .05, ''), ('sy', 'Skala pionowa', .05, 20, 2, .05, ''),
    ('margin', 'Margines od krawędzi', 0, 200, 2, .25, ' mm'), ('margin_holes', 'Margines od otworów', 0, 200, 2, .25, ' mm'),
    ('radius', 'Promień zaokrąglenia', 0, 50, 2, .1, ' mm'), ('draft', 'Kąt nachylenia ścianek', 0, 80, 1, 5, ' °'),
    ('nx', 'Liczba powtórzeń poziomo (0 = auto)', 0, 5000, 0, 1, ''), ('ny', 'Liczba powtórzeń pionowo (0 = auto)', 0, 5000, 0, 1, ''),
    ('density', 'Gęstość wzoru', .1, 5, 2, .1, '×'), ('randomness', 'Stopień losowości', 0, 1, 2, .05, ''), ('seed', 'Seed generatora', 0, 999999, 0, 1, ''),
    ('groove_angle', 'Kąt przecinania rowków', 10, 170, 1, 5, ' °'), ('groove', 'Szerokość rowka', .05, 50, 2, .1, ' mm'),
    ('trap', 'Szerokość górna trapezu (× podstawa)', .05, .95, 2, .05, ''), ('helix', 'Kąt spirali', 1, 89, 1, 5, ' °'), ('starts', 'Liczba równoległych spiral', 1, 24, 0, 1, ''),
    ('row_shift', 'Przesunięcie kolejnych rzędów', 0, 100, 1, 5, ' %'), ('tri_ratio', 'Proporcja trójkąta (nierównoboczny)', .3, 4, 2, .1, ''),
    ('cells', 'Liczba komórek (0 = z wielkości)', 0, 50000, 0, 1, ''), ('irregular', 'Stopień nieregularności', 0, 1, 2, .05, ''),
    ('corner', 'Zaokrąglenie narożników komórek', 0, 20, 2, .1, ' mm'), ('sides', 'Liczba boków', 3, 24, 0, 1, ''),
    ('trunc', 'Ścięcie wierzchołka (0 = szczyt)', 0, .95, 2, .05, ''), ('edge_round', 'Zaokrąglenie krawędzi wypustek', 0, 20, 2, .05, ' mm'),
    ('amp', 'Amplituda fali', .02, 50, 2, .05, ' mm'), ('wavelength', 'Długość fali', .5, 500, 2, .5, ' mm'), ('wave_dir', 'Kierunek fali', -180, 180, 1, 5, ' °'),
    ('wave2_dir', 'Kierunek drugiej fali', -180, 180, 1, 5, ' °'), ('wave2_amp', 'Amplituda drugiej fali', .02, 50, 2, .05, ' mm'),
    ('wave2_len', 'Długość drugiej fali', .5, 500, 2, .5, ' mm'), ('bump_n', 'Wypustek w komórce (1, 2, 3...)', 1, 6, 0, 1, ''),
    ('bump_len', 'Długość wypustki', .5, 200, 2, .5, ' mm'), ('bump_w', 'Szerokość wypustki', .2, 100, 2, .2, ' mm'), ('bump_gap', 'Odstęp wypustek', 0, 50, 2, .2, ' mm'),
    ('bump_angle', 'Kąt rozmieszczenia', -90, 90, 1, 5, ' °'), ('arm_angle', 'Kąt ramion V', 5, 85, 1, 5, ' °'), ('arm_len', 'Długość ramienia', .5, 200, 2, .5, ' mm'),
    ('arm_w', 'Szerokość ramienia', .1, 50, 2, .1, ' mm'), ('ring_r0', 'Promień początkowy', 0, 1000, 2, .5, ' mm'), ('ring_gap', 'Odstęp między pierścieniami', .1, 200, 2, .25, ' mm'),
    ('ring_w', 'Szerokość pierścienia', .05, 100, 2, .1, ' mm'), ('ring_a0', 'Początek łuku', -360, 360, 1, 5, ' °'), ('ring_a1', 'Koniec łuku', -360, 360, 1, 5, ' °'),
    ('ring_cx', 'Środek wzoru X', -1e4, 1e4, 2, .5, ' mm'), ('ring_cy', 'Środek wzoru Y', -1e4, 1e4, 2, .5, ' mm'), ('ring_n', 'Liczba pierścieni (0 = auto)', 0, 2000, 0, 1, ''),
    ('overlap', 'Zachodzenie łusek', 0, .9, 2, .05, ''), ('tilt', 'Nachylenie łusek', -80, 80, 1, 5, ' °'), ('weave_gap', 'Odstęp pasów plecionki', 0, 20, 2, .1, ' mm'),
    ('strip', 'Szerokość pasa plecionki', .1, 100, 2, .1, ' mm'), ('ham_min', 'Najmniejsza średnica zagłębienia', .2, 100, 2, .25, ' mm'),
    ('ham_max', 'Największa średnica zagłębienia', .2, 100, 2, .25, ' mm'), ('ham_dmin', 'Najmniejsza głębokość', .02, 50, 2, .05, ' mm'),
    ('ham_dmax', 'Największa głębokość', .02, 50, 2, .05, ' mm'), ('c_rot', 'Obrót elementu własnego', -360, 360, 1, 5, ' °'), ('c_scale', 'Skala elementu własnego', .05, 50, 2, .05, '×'),
    ('c_count', 'Liczba kopii (promieniowo)', 1, 500, 0, 1, ''), ('mixed_pct', 'Udział zagłębień (mieszana)', 0, 100, 0, 5, ' %'),
    ('min_wall', 'Minimalna pozostała grubość ścianki', .05, 50, 2, .1, ' mm'), ('tol', 'Tolerancja aproksymacji', .005, 1, 3, .01, ' mm'))

USE = {  # parametry specyficzne dla wzoru (pozostałe ukrywane)
    'knurl_cross': ('size', 'groove', 'groove_angle', 'height', 'depth', 'tip', 'radius', 'draft'),
    'knurl_straight': ('size', 'width', 'profile', 'trap', 'height', 'depth', 'radius'),
    'knurl_spiral': ('size', 'width', 'profile', 'trap', 'hand', 'helix', 'starts', 'height', 'depth'),
    'honeycomb': ('size', 'wall', 'fill', 'row_shift', 'height', 'depth', 'radius', 'draft'),
    'dots': ('size', 'dot_shape', 'dot_layout', 'row_shift', 'height', 'depth', 'trunc'),
    'pyramids': ('size', 'sides', 'trunc', 'edge_round', 'height', 'depth', 'row_shift'),
    'waves': ('wave_type', 'amp', 'wavelength', 'wave_dir', 'wave2', 'wave2_dir', 'wave2_amp', 'wave2_len'),
    'voronoi': ('size', 'cells', 'wall', 'irregular', 'corner', 'fill', 'height', 'depth'),
    'checker': ('bump_n', 'bump_shape', 'bump_len', 'bump_w', 'bump_gap', 'bump_angle', 'height', 'depth', 'draft'),
    'herringbone': ('arm_angle', 'arm_len', 'arm_w', 'alternate', 'height', 'depth'),
    'rings': ('ring_r0', 'ring_gap', 'ring_w', 'ring_a0', 'ring_a1', 'ring_cx', 'ring_cy', 'ring_n', 'profile', 'height', 'depth'),
    'scales': ('size', 'scale_shape', 'sides', 'overlap', 'tilt', 'height', 'depth', 'row_shift'),
    'weave': ('weave_kind', 'strip', 'weave_gap', 'height', 'depth'),
    'hammered': ('ham_min', 'ham_max', 'ham_dmin', 'ham_dmax', 'randomness', 'density'),
    'triangles': ('size', 'tri_kind', 'tri_ratio', 'fill', 'wall', 'alternate', 'height', 'depth'),
    'custom': ('custom_src', 'c_layout', 'c_rot', 'c_scale', 'c_count', 'size', 'height', 'depth'),
    'image': ('height', 'depth'),
}
COMMON_USE = ('px', 'py', 'angle', 'ox', 'oy', 'sx', 'sy', 'margin', 'margin_holes', 'nx', 'ny', 'density', 'randomness', 'seed')
COMBO = {
    'tip': {'sharp': 'Ostre wierzchołki', 'round': 'Zaokrąglone wierzchołki'},
    'profile': {'rect': 'Profil prostokątny', 'tri': 'Profil trójkątny', 'trap': 'Profil trapezowy', 'round': 'Profil półokrągły'},
    'hand': {'right': 'Prawoskrętna', 'left': 'Lewoskrętna'},
    'fill': {'solid': 'Pełne wypustki', 'outline': 'Same obrysy'},
    'dot_shape': {'sphere': 'Kulista', 'hemisphere': 'Półkulista', 'cap': 'Czasza (z wysokością)', 'cyl': 'Cylindryczna', 'cone': 'Stożkowa'},
    'dot_layout': {'rect': 'Rozmieszczenie prostokątne', 'stagger': 'Rozmieszczenie naprzemienne', 'random': 'Rozmieszczenie losowe'},
    'wave_type': {'sine': 'Fala sinusoidalna', 'tri': 'Fala trójkątna', 'square': 'Fala prostokątna'},
    'bump_shape': {'oval': 'Owalne', 'rect': 'Prostokątne', 'rhomb': 'Romboidalne'},
    'scale_shape': {'round': 'Okrągłe', 'oval': 'Owalne', 'rhomb': 'Romboidalne', 'poly': 'Wielokątne'},
    'weave_kind': {'straight': 'Prosta', 'diagonal': 'Ukośna', 'multi': 'Wielokierunkowa'},
    'tri_kind': {'equilateral': 'Równoboczne', 'scalene': 'Nierównoboczne'},
    'custom_src': {'sketch': 'Szkic 2D', 'file': 'Plik SVG / DXF', 'solid': 'Bryła jako element'},
    'c_layout': {'rect': 'Rozmieszczenie prostokątne', 'radial': 'Rozmieszczenie promieniowe', 'stagger': 'Rozmieszczenie naprzemienne', 'random': 'Rozmieszczenie losowe'},
    'mixed_rule': {'alternate': 'Naprzemiennie', 'random': 'Losowo', 'rows': 'Rzędami'},
    'accuracy': {'exact': 'Dokładny B-Rep', 'optimized': 'Zoptymalizowany B-Rep', 'mesh': 'Siatkowy (STL / 3MF)'},
    'fit': {'exact': 'Dokładny rozstaw', 'auto': 'Dopasuj rozstaw do powierzchni', 'count': 'Dopasuj do liczby powtórzeń', 'center': 'Wyśrodkuj wzór',
            'edge': 'Dopasuj do krawędzi powierzchni', 'start': 'Rozpocznij od wskazanego punktu', 'fill': 'Wypełnij całą powierzchnię',
            'proportion': 'Zachowaj proporcje wzoru', 'stretch': 'Rozciągnij niezależnie w dwóch kierunkach'},
    'boundary': {'clip': 'Przycinaj elementy do granicy', 'remove': 'Usuwaj niepełne elementy', 'fit': 'Dopasuj wzór bez przecinania elementów'},
}
BOOL = {'wave2': 'Nałóż drugą falę', 'alternate': 'Naprzemienne odwracanie', 'reverse': 'Odwróć kierunek', 'mirror': 'Odbicie lustrzane', 'protect_wall': 'Chroń minimalną grubość ścianki'}


# ---------------------------------------------------------------------------------------------- pomocnicze
def rot(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s], [s, c]])


def circle_pts(r, n=None, a0=0.0, a1=2 * math.pi, tol=.02):
    if n is None:
        n = max(8, int(math.ceil(abs(a1 - a0) / (2 * math.acos(max(0.0, 1 - tol / max(r, tol * 2)))))))
        n = min(n, 96)
    full = abs(abs(a1 - a0) - 2 * math.pi) < 1e-9
    t = np.linspace(a0, a1, n, endpoint=not full)
    return np.c_[r * np.cos(t), r * np.sin(t)]


def regular(n, r, a0=0.0):
    t = a0 + np.arange(n) * 2 * math.pi / n
    return np.c_[r * np.cos(t), r * np.sin(t)]


def round_poly(P, r, n=4):
    """Wielokąt z zaokrąglonymi narożnikami (łuki z n odcinków)."""
    P = np.asarray(P, float)
    if r <= 1e-9 or len(P) < 3:
        return P
    out = []
    m = len(P)
    for i in range(m):
        a, b, c = P[i - 1], P[i], P[(i + 1) % m]
        u, v = a - b, c - b
        lu, lv = np.linalg.norm(u), np.linalg.norm(v)
        if lu < 1e-9 or lv < 1e-9:
            out.append(b)
            continue
        u, v = u / lu, v / lv
        ang = math.acos(max(-1.0, min(1.0, float(u @ v))))
        if ang < 1e-3 or abs(math.pi - ang) < 1e-3:
            out.append(b)
            continue
        t = min(r / math.tan(ang / 2), lu / 2, lv / 2)
        rr = t * math.tan(ang / 2)
        p0, p1 = b + u * t, b + v * t
        bis = (u + v)
        bis /= np.linalg.norm(bis)
        cen = b + bis * (rr / math.sin(ang / 2))
        a0 = math.atan2(*(p0 - cen)[::-1])
        a1 = math.atan2(*(p1 - cen)[::-1])
        d = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        for s in np.linspace(0, 1, n + 1):
            out.append(cen + rr * np.array([math.cos(a0 + d * s), math.sin(a0 + d * s)]))
    return np.array(out)


def inset(P, d):
    """Pomniejszenie wypukłego wielokąta o d (przesunięcie boków)."""
    from . import vent_layout as vl
    return vl.inset_convex(P, d)


def stadium(L, W, n=6):
    """Owal (prostokąt z półokrągłymi końcami) o długości L i szerokości W wzdłuż osi x."""
    r = W / 2
    a = max(L / 2 - r, 0.0)
    t1 = np.linspace(-math.pi / 2, math.pi / 2, n + 1)
    t2 = t1 + math.pi
    return np.vstack([np.c_[a + r * np.cos(t1), r * np.sin(t1)], np.c_[-a + r * np.cos(t2), r * np.sin(t2)]])


def rect(L, W):
    return np.array([[-L / 2, -W / 2], [L / 2, -W / 2], [L / 2, W / 2], [-L / 2, W / 2]])


def rhomb(L, W):
    return np.array([[-L / 2, 0], [0, -W / 2], [L / 2, 0], [0, W / 2]])


def fnum(p, key):
    return float(p[key]) if p.get(key) is not None else float(DEFAULTS[key])


_REC = []


def default_pitch(p):
    """Rozstaw, który generator wybiera dla px = 0 (zależy od wzoru) - do dopasowania liczby powtórzeń na walcu."""
    q = dict(p, px=0.0, py=0.0, density=1.0, custom_loops=p.get('custom_loops'))
    _REC.clear()
    try:
        generate(q, Frame((0, 0), 0.0, 1.0, 1.0, False), np.array([-1.0, -1.0]), np.array([1.0, 1.0]))
    except Exception:
        pass
    r = _REC[0] if _REC else float(p.get('size') or 1.0)
    _REC.clear()
    return r


def pitch(p, default):
    _REC.append(float(default))
    px = fnum(p, 'px') or default
    py = fnum(p, 'py') or px
    dens = max(.05, fnum(p, 'density'))
    return px / dens, py / dens


class Frame:
    """Układ wzoru: dziedzina = O + R(angle)·(S·(u, v)); wzór leży w (u, v)."""

    def __init__(self, o, angle, sx=1.0, sy=1.0, mirror=False):
        self.o = np.asarray(o, float)
        self.R = rot(math.radians(angle))
        self.S = np.array([sx * (-1 if mirror else 1), sy], float)

    def fwd(self, Q):
        Q = np.asarray(Q, float)
        return self.o + (Q * self.S) @ self.R.T

    def inv(self, P):
        P = np.asarray(P, float)
        return ((P - self.o) @ self.R) / self.S

    def uv_box(self, lo, hi):
        c = np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]])
        q = self.inv(c)
        return q.min(0), q.max(0)


def lattice(frame, lo, hi, dx, dy, shift_row=0.0, centered=True, extra=1):
    """Węzły siatki w układzie wzoru pokrywające prostokąt lo-hi: tablice (i, j, u, v)."""
    a, b = frame.uv_box(lo, hi)
    dx, dy = max(abs(dx), 1e-3), max(abs(dy), 1e-3)
    i0, i1 = int(math.floor(a[0] / dx)) - extra, int(math.ceil(b[0] / dx)) + extra
    j0, j1 = int(math.floor(a[1] / dy)) - extra, int(math.ceil(b[1] / dy)) + extra
    I, J = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing='ij')
    I, J = I.ravel(), J.ravel()
    u = I * dx + (J % 2) * dx * shift_row / 100.0
    v = J * dy
    return I, J, u, v


def _wrap(frame, els):
    f = lambda Q: frame.fwd(Q)
    out = [e.moved(f) for e in els]
    if frame.S[0] * frame.S[1] < 0:                                   # odbicie - kierunki obrotu elementów odwrócone
        for e in out:
            e.ang = -e.ang
    return out


def _rnd(p, n, scale=1.0):
    rng = np.random.default_rng(int(p.get('seed', 1)))
    return rng.random((n, 2)) - .5, rng


# ---------------------------------------------------------------------------------------------- wzory
def gen_knurl_cross(p, fr, lo, hi):
    """Radełkowanie krzyżowe: romby (przecięcie dwóch rodzin rowków pod kątem groove_angle) zakończone ostro albo zaokrąglone."""
    pt = max(fnum(p, 'size'), .2)
    pit = pitch(p, pt)[0]
    ga = math.radians(max(10.0, min(170.0, fnum(p, 'groove_angle'))))
    gw = min(fnum(p, 'groove'), pit * .8)
    half = ga / 2
    # rodziny rowków nachylone ±half względem osi x; odstęp prostopadły pit → rozstaw rombów dx = pit/sin(half), dy = pit/cos(half)
    dx, dy = pit / math.sin(half), pit / math.cos(half)
    I, J, u, v = lattice(fr, lo, hi, dx, dy / 2, 0.0)
    keep = (I + J) % 2 == 0
    els = []
    L, W = dx - gw / math.sin(half), dy - gw / math.cos(half)
    L, W = max(L, pit * .15), max(W, pit * .15)
    base = rhomb(L, W)
    if p.get('tip') == 'round' or fnum(p, 'radius') > 0:
        base = round_poly(base, fnum(p, 'radius') or min(L, W) * .12)
    k = 0.0 if p.get('tip') != 'round' else .25
    for i, j, a, b in zip(I[keep], J[keep], u[keep], v[keep]):
        els.append(El('poly', (a, b), poly=base + (a, b), k=k, extra=(i, j)))
    return _wrap(fr, els)


def _bar(c, ang, L, w, prof, trap, idx=0, **kw):
    d = np.array([math.cos(ang), math.sin(ang)])
    c = np.asarray(c, float)
    return El('bar', c, p0=c - d * L / 2, p1=c + d * L / 2, w=w, prof=prof, k=trap, idx=idx, **kw)


def gen_knurl_straight(p, fr, lo, hi):
    w = fnum(p, 'width')
    pit = max(pitch(p, fnum(p, 'size'))[0], w * 1.02)
    a, b = fr.uv_box(lo, hi)
    L = float(np.linalg.norm(b - a)) + 4
    n0, n1 = int(math.floor(a[0] / pit)) - 1, int(math.ceil(b[0] / pit)) + 1
    mid = (a[1] + b[1]) / 2
    prof = p.get('profile', 'rect')
    return _wrap(fr, [_bar((i * pit, mid), math.pi / 2, L, w, prof, fnum(p, 'trap'), idx=i) for i in range(n0, n1 + 1)])


def gen_knurl_spiral(p, fr, lo, hi):
    """Spirala w dziedzinie (po rozwinięciu walca) to proste pod kątem helix do osi; hand - zwrot; starts - wiele równoległych."""
    w = fnum(p, 'width')
    pit = max(pitch(p, fnum(p, 'size'))[0], w * 1.02)
    ang = math.radians(fnum(p, 'helix')) * (1 if p.get('hand') != 'left' else -1)
    a, b = fr.uv_box(lo, hi)
    L = float(np.linalg.norm(b - a)) + 4
    starts = max(1, int(fnum(p, 'starts')))
    dist = pit * starts                                               # odstęp między rowkami tej samej spirali
    n0, n1 = int(math.floor(-L / dist)) - 1, int(math.ceil(L / dist)) + 1
    mid = (a + b) / 2
    nvec = np.array([-math.sin(ang), math.cos(ang)])                  # prostopadle do kierunku rowków
    els = []
    for s in range(starts):
        for i in range(n0, n1 + 1):
            c = mid + nvec * (i * dist + s * pit)
            els.append(_bar(c, ang, L, w, p.get('profile', 'rect'), fnum(p, 'trap'), idx=i * starts + s))
    return _wrap(fr, els)


def hexagon(r, a0=math.pi / 6):
    return regular(6, r, a0)


def gen_honeycomb(p, fr, lo, hi):
    s = max(fnum(p, 'size'), .5)                                      # wielkość = średnica okręgu opisanego komórki (wierzchołek-wierzchołek)
    R = s / 2 / max(1.0, 1.0)
    pit = pitch(p, s)
    # heksagony „płaskie u góry”: odstęp środków poziomo = √3·R, pionowo = 1.5·R; przesunięcie co drugiego rzędu o połowę
    dx, dy = math.sqrt(3) * R * pit[0] / s, 1.5 * R * pit[1] / s
    I, J, u, v = lattice(fr, lo, hi, dx, dy, fnum(p, 'row_shift'))
    wall = min(fnum(p, 'wall'), R * .9)
    hexa = hexagon(R, math.pi / 6)
    outer = inset(hexa, wall / 2) if wall > 0 else hexa
    rr = fnum(p, 'radius')
    els = []
    for a, b, i, j in zip(u, v, I, J):
        if p.get('fill') == 'outline':
            inner = inset(hexa, wall / 2 + max(wall, .2))
            if len(inner) < 3:
                continue
            els.append(El('poly', (a, b), poly=outer + (a, b), holes=[inner + (a, b)], extra=(i, j)))
        else:
            o = round_poly(outer, rr) if rr > 0 else outer
            els.append(El('poly', (a, b), poly=o + (a, b), k=1.0 if fnum(p, 'draft') <= 0 else max(.2, 1 - math.tan(math.radians(fnum(p, 'draft'))) * fnum(p, 'height') / max(R, .1)), extra=(i, j)))
    return _wrap(fr, els)


def gen_dots(p, fr, lo, hi):
    d = max(fnum(p, 'size'), .2)
    pit = pitch(p, d * 1.6)
    lay = p.get('dot_layout', 'rect')
    els = []
    if lay == 'random':
        a, b = fr.uv_box(lo, hi)
        area = float(np.prod(b - a))
        n = max(1, int(area / (pit[0] * pit[1]) * .8))
        rng = np.random.default_rng(int(p.get('seed', 1)))
        n = min(n, 200000)
        Q = a + rng.random((n, 2)) * (b - a)
        Q = _poisson_filter(Q, d * 1.05)
        for q in Q:
            els.append(El('dome', q, shape=p.get('dot_shape', 'hemisphere'), d=d, k=max(fnum(p, 'trunc'), 0.0)))
    else:
        I, J, u, v = lattice(fr, lo, hi, pit[0], pit[1], 50.0 if lay == 'stagger' else 0.0)
        for a, b in zip(u, v):
            els.append(El('dome', (a, b), shape=p.get('dot_shape', 'hemisphere'), d=d, k=fnum(p, 'trunc') or .5))
    return _wrap(fr, els)


def _poisson_filter(Q, r):
    """Zostawia punkty oddalone od siebie o co najmniej r (siatka przestrzenna)."""
    cell = r
    grid = {}
    out = []
    for q in Q:
        key = (int(q[0] // cell), int(q[1] // cell))
        ok = True
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for o in grid.get((key[0] + di, key[1] + dj), ()):
                    if (o[0] - q[0]) ** 2 + (o[1] - q[1]) ** 2 < r * r:
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                break
        if ok:
            grid.setdefault(key, []).append(q)
            out.append(q)
    return np.array(out)


def gen_pyramids(p, fr, lo, hi):
    b = max(fnum(p, 'size'), .3)
    n = int(fnum(p, 'sides')) or 4
    pit = pitch(p, b)
    kt = fnum(p, 'trunc')
    els = []
    if n == 4:
        I, J, u, v = lattice(fr, lo, hi, pit[0], pit[1], fnum(p, 'row_shift') if p.get('row_shift') not in (None, 50.0) else 0.0)
        base = rect(b, b)
        for a, c in zip(u, v):
            els.append(El('poly', (a, c), poly=base + (a, c), k=kt))
    elif n == 3:
        h = b * math.sqrt(3) / 2
        I, J, u, v = lattice(fr, lo, hi, pit[0] / 2, pit[1] * math.sqrt(3) / 2, 0.0)
        for i, j, a, c in zip(I, J, u, v):
            up = (i + j) % 2 == 0
            tri = regular(3, b / math.sqrt(3), math.pi / 2 if up else -math.pi / 2)
            els.append(El('poly', (a, c), poly=tri + (a, c), k=kt))
    else:
        R = b / 2 / math.cos(math.pi / n) if n > 2 else b / 2
        step = 2 * R * math.cos(math.pi / n)
        I, J, u, v = lattice(fr, lo, hi, step * pit[0] / b, step * pit[1] / b * (.87 if n == 6 else 1.0), 50.0 if n == 6 else 0.0)
        poly = regular(n, R, math.pi / n if n % 2 == 0 else math.pi / 2)
        for a, c in zip(u, v):
            els.append(El('poly', (a, c), poly=poly + (a, c), k=kt))
    return _wrap(fr, els)


def wave_profile(kind, A, lam, nseg=24):
    """Jeden okres fali: punkty (s, z), s ∈ [0, lam]."""
    if kind == 'tri':
        s = np.array([0, lam / 4, 3 * lam / 4, lam])
        z = np.array([0, A, -A, 0])
        return np.c_[s, z]
    if kind == 'square':
        s = np.array([0, 0, lam / 2, lam / 2, lam])
        z = np.array([-A, A, A, -A, -A])
        return np.c_[s, z]
    s = np.linspace(0, lam, nseg + 1)
    return np.c_[s, A * np.sin(2 * math.pi * s / lam)]


def wave_field(p, X, Y):
    """Wysokość fal w punktach dziedziny (z ≤ amplituda); jedna albo dwie fale nałożone."""
    def one(kind, A, lam, dirdeg):
        d = math.radians(dirdeg)
        s = (X * math.cos(d) + Y * math.sin(d)) / lam
        ph = s - np.floor(s)
        if kind == 'tri':
            return A * (1 - 4 * np.abs(((ph - .25) % 1) - .5))
        if kind == 'square':
            return A * np.where(ph < .5, 1.0, -1.0)
        return A * np.sin(2 * math.pi * s)
    z = one(p.get('wave_type', 'sine'), fnum(p, 'amp'), max(fnum(p, 'wavelength'), .3), fnum(p, 'wave_dir'))
    if p.get('wave2'):
        z = z + one(p.get('wave_type', 'sine'), fnum(p, 'wave2_amp'), max(fnum(p, 'wave2_len'), .3), fnum(p, 'wave2_dir'))
    return z


def gen_waves(p, fr, lo, hi):
    """Fale to pole wysokości - rzeczywistą geometrię buduje tex_relief (powierzchnia B-Spline albo wytłoczenie profilu fali)."""
    return [El('field', (lo + hi) / 2, extra=dict(kind='waves'))]


def gen_voronoi(p, fr, lo, hi):
    from . import vent_layout as vl
    a, b = fr.uv_box(lo, hi)
    size = max(fnum(p, 'size'), .8) / max(.2, fnum(p, 'density'))
    cells = int(fnum(p, 'cells'))
    rng = np.random.default_rng(int(p.get('seed', 1)))
    n = cells or max(4, int(np.prod(b - a + 2 * size) / (size * size * .87)))
    n = min(n, 60000)
    irr = max(0.0, min(1.0, fnum(p, 'irregular')))
    if cells:
        P = a + rng.random((n, 2)) * (b - a)
    else:                                                             # siatka sześciokątna zaburzona o irr - komórki równomiernej wielkości
        k = int(math.sqrt(n)) + 2
        dx = size
        dy = size * .87
        I, J = np.meshgrid(np.arange(-2, int((b[0] - a[0]) / dx) + 3), np.arange(-2, int((b[1] - a[1]) / dy) + 3), indexing='ij')
        P = np.c_[a[0] + (I.ravel() + (J.ravel() % 2) * .5) * dx, a[1] + J.ravel() * dy] + (rng.random((I.size, 2)) - .5) * size * irr
    cell_lists = vl.voronoi_cells(P, a - 2 * size, b + 2 * size)
    wall = fnum(p, 'wall')
    els = []
    for s, poly in zip(P, cell_lists):
        if len(poly) < 3:
            continue
        if not (a[0] - size <= s[0] <= b[0] + size and a[1] - size <= s[1] <= b[1] + size):
            continue
        q = vl.inset_convex(poly, wall / 2)
        if len(q) < 3 or abs(_area(q)) < 1e-4:
            continue
        q = round_poly(q, fnum(p, 'corner')) if fnum(p, 'corner') > 0 else q
        if p.get('fill') == 'outline':
            inner = vl.inset_convex(poly, wall / 2 + max(wall, .3))
            if len(inner) < 3:
                continue
            els.append(El('poly', q.mean(0), poly=q, holes=[round_poly(inner, fnum(p, 'corner')) if fnum(p, 'corner') > 0 else inner]))
        else:
            els.append(El('poly', q.mean(0), poly=q))
    return _wrap(fr, els)


def _area(P):
    x, y = P[:, 0], P[:, 1]
    return float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)) / 2


def gen_checker(p, fr, lo, hi):
    """Blacha ryflowana: w komórce n równoległych wypustek (owalnych / prostokątnych / romboidalnych); sąsiednie komórki
    obrócone o ±bump_angle (naprzemiennie), jak w blasze „kwintet”."""
    L, W = fnum(p, 'bump_len'), fnum(p, 'bump_w')
    n = max(1, int(fnum(p, 'bump_n')))
    gap = fnum(p, 'bump_gap')
    cell = max(L, n * W + (n - 1) * gap) * 1.05 + gap
    pit = pitch(p, cell)
    I, J, u, v = lattice(fr, lo, hi, pit[0], pit[1], 0.0)
    ang = math.radians(fnum(p, 'bump_angle'))
    shape = {'oval': stadium, 'rect': rect, 'rhomb': rhomb}[p.get('bump_shape', 'oval')]
    base = shape(L, W)
    if shape is stadium:
        base = stadium(L, W, 5)
    els = []
    for i, j, a, b in zip(I, J, u, v):
        th = ang if (i + j) % 2 == 0 else ang + math.pi / 2
        for m in range(n):
            off = (m - (n - 1) / 2) * (W + gap)
            c = np.array([a, b]) + rot(th) @ np.array([0.0, off])
            q = (base @ rot(th).T) + c
            dr = math.tan(math.radians(fnum(p, 'draft')))
            els.append(El('poly', c, poly=q, k=max(.15, 1 - dr * fnum(p, 'height') / max(W, .2)) if dr > 0 else 1.0, extra=(i, j, m)))
    return _wrap(fr, els)


def gen_herringbone(p, fr, lo, hi):
    ang = math.radians(fnum(p, 'arm_angle'))
    L, W = fnum(p, 'arm_len'), fnum(p, 'arm_w')
    pit = pitch(p, L * math.cos(ang) * 2.0 + W)
    dxv = 2 * L * math.sin(ang) + W * 1.2                             # szerokość V
    dyv = max(W * 1.15 / max(math.cos(ang), .2) + 0.0, pit[1] * .5)
    dxv = max(dxv, pit[0])
    I, J, u, v = lattice(fr, lo, hi, dxv, max(dyv, W * 1.2), 0.0)
    els = []
    for i, j, a, b in zip(I, J, u, v):
        flip = p.get('alternate', True) and (j % 2 == 1)
        s = -1 if flip else 1
        # V: dwa ramiona zbiegające w punkcie (a, b); polilinia z grubością W jako wielokąt
        pts = np.array([[-L * math.sin(ang), s * L * math.cos(ang)], [0.0, 0.0], [L * math.sin(ang), s * L * math.cos(ang)]])
        poly = _thick_polyline(pts, W)
        if poly is None:
            continue
        els.append(El('poly', (a, b), poly=poly + (a, b), extra=(i, j)))
    return _wrap(fr, els)


def _thick_polyline(pts, w):
    """Wielokąt otaczający polilinię o grubości w (złącza ostre, bez samoprzecięć dla łamanych o 2 ramionach)."""
    pts = np.asarray(pts, float)
    n = len(pts)
    left, right = [], []
    for i in range(n):
        if i == 0:
            d = pts[1] - pts[0]
            nrm = np.array([-d[1], d[0]]) / max(np.linalg.norm(d), 1e-12)
            off = nrm * w / 2
        elif i == n - 1:
            d = pts[-1] - pts[-2]
            nrm = np.array([-d[1], d[0]]) / max(np.linalg.norm(d), 1e-12)
            off = nrm * w / 2
        else:
            d1 = pts[i] - pts[i - 1]
            d2 = pts[i + 1] - pts[i]
            n1 = np.array([-d1[1], d1[0]]) / max(np.linalg.norm(d1), 1e-12)
            n2 = np.array([-d2[1], d2[0]]) / max(np.linalg.norm(d2), 1e-12)
            m = n1 + n2
            nm = np.linalg.norm(m)
            if nm < 1e-9:
                return None
            off = m / nm * (w / 2) / max(float(n1 @ (m / nm)), .2)
        left.append(pts[i] + off)
        right.append(pts[i] - off)
    poly = np.array(left + right[::-1])
    return poly


def gen_rings(p, fr_unused, lo, hi):
    """Pierścienie koncentryczne wokół środka (ring_cx, ring_cy) w dziedzinie (bez obrotu wzoru - jest symetryczny)."""
    c = np.array([fnum(p, 'ring_cx'), fnum(p, 'ring_cy')]) + [fnum(p, 'ox'), fnum(p, 'oy')]
    r0, gap, w = fnum(p, 'ring_r0'), max(fnum(p, 'ring_gap'), .05), fnum(p, 'ring_w')
    corners = np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]])
    rmax = float(np.linalg.norm(corners - c, axis=1).max()) + w
    step = (w + gap) / max(.05, fnum(p, 'density'))
    n = int(fnum(p, 'ring_n')) or int(max(0, (rmax - r0) / step)) + 1
    a0, a1 = math.radians(fnum(p, 'ring_a0')), math.radians(fnum(p, 'ring_a1'))
    full = abs(abs(a1 - a0) - 2 * math.pi) < 1e-6 or abs(a1 - a0) >= 2 * math.pi
    if not full and a1 < a0:
        a1 += 2 * math.pi
    els = []
    for i in range(n):
        r = r0 + i * step
        if r > rmax:
            break
        ro, ri = r + w / 2, max(r - w / 2, 0.0)
        if full:
            outer = circle_pts(ro, tol=max(.01, fnum(p, 'tol') * .5))
            holes = [circle_pts(ri, tol=max(.01, fnum(p, 'tol') * .5))] if ri > 1e-6 else []
            els.append(El('poly', c, poly=outer + c, holes=[h + c for h in holes], extra=dict(ring=(float(r), float(w)), centre=c), idx=i))
        else:
            ang = np.linspace(a0, a1, max(8, int(abs(a1 - a0) * ro / .5)))
            outer = np.c_[ro * np.cos(ang), ro * np.sin(ang)]
            inner = np.c_[ri * np.cos(ang[::-1]), ri * np.sin(ang[::-1])] if ri > 1e-6 else np.zeros((1, 2))
            q = np.vstack([outer, inner]) + c
            els.append(El('poly', c, poly=q, idx=i, extra=dict(ring=None, centre=c)))
    return els


def gen_scales(p, fr, lo, hi):
    d = max(fnum(p, 'size'), .5)
    ov = max(0.0, min(.9, fnum(p, 'overlap')))
    pit = pitch(p, d)
    dx = pit[0]
    dy = pit[1] * (1 - ov) * (.5 if p.get('scale_shape') == 'round' else .5)
    I, J, u, v = lattice(fr, lo, hi, dx, max(dy, .1), fnum(p, 'row_shift'))
    shape = p.get('scale_shape', 'round')
    if shape == 'round':
        base = circle_pts(d / 2, tol=max(.05, fnum(p, 'tol')))
    elif shape == 'oval':
        base = stadium(d * 1.25, d, 6)
    elif shape == 'rhomb':
        base = rhomb(d, d * 1.2)
    else:
        base = regular(max(3, int(fnum(p, 'sides'))), d / 2, math.pi / 2)
    tilt = math.tan(math.radians(fnum(p, 'tilt'))) * fnum(p, 'height')
    els = []
    sgn = -1 if p.get('reverse') else 1
    from . import tex_engine as te
    shape0 = None
    if ov > 1e-6:                                                      # łuska leży pod łuskami następnego rzędu: widoczna część = bez nich
        offs = [(-dx / 2, dy * sgn), (dx / 2, dy * sgn)] if fnum(p, 'row_shift') > 0 else [(0.0, dy * sgn)]
        gapc = .04
        cc = base.mean(0)
        infl = cc + (base - cc) * (1 + 2 * gapc / max(d, .1)) if len(base) else base
        shape0 = te.poly_diff(base, [infl + np.array(o) for o in offs])     # kształt łuski jest wszędzie taki sam - liczony raz
    for i, j, a, b in zip(I, J, u, v):
        c = np.array([a, b])
        if shape0 is not None:
            for o, hs in shape0:
                els.append(El('poly', c + o.mean(0), poly=o + c, holes=[h + c for h in hs], tilt=(0.0, sgn * tilt), extra=(i, j), idx=int(j)))
        else:
            els.append(El('poly', c, poly=base + c, tilt=(0.0, sgn * tilt), extra=(i, j), idx=int(j)))
    return _wrap(fr, els)


def gen_weave(p, fr, lo, hi):
    """Plecionka: w każdej komórce dwa pasy (poziomy i pionowy); na skrzyżowaniach przeplot - pas „nad” ma pełną wysokość, pas „pod” połowę."""
    w = fnum(p, 'strip')
    gap = fnum(p, 'weave_gap')
    cell = w + gap
    cell = max(cell, w * 1.02) / max(.2, fnum(p, 'density'))
    kind = p.get('weave_kind', 'straight')
    ang0 = 45.0 if kind == 'diagonal' else 0.0
    if kind == 'diagonal':
        fr = Frame(fr.o, math.degrees(math.atan2(fr.R[1, 0], fr.R[0, 0])) + 45.0, fr.S[0], fr.S[1])
    I, J, u, v = lattice(fr, lo, hi, cell, cell, 0.0)
    els = []
    fl = max(.3, 1.0 - gap / cell)
    for i, j, a, b in zip(I, J, u, v):
        over = (i + j) % 2 == 0
        els.append(El('poly', (a, b), poly=rect(cell * 1.001, w) + (a, b), hs=1.0 if over else .5, extra=('h', i, j)))
        els.append(El('poly', (a, b), poly=rect(w, cell * 1.001) + (a, b), hs=.5 if over else 1.0, extra=('v', i, j)))
    out = _wrap(fr, els)
    if kind == 'multi':                                               # trzeci kierunek (60°): pasy o przeplocie co trzeci
        fr2 = Frame(fr.o, math.degrees(math.atan2(fr.R[1, 0], fr.R[0, 0])) + 60.0, fr.S[0], fr.S[1])
        I2, J2, u2, v2 = lattice(fr2, lo, hi, cell * 1.5, cell * 1.5, 0.0)
        els2 = [El('poly', (a, b), poly=rect(cell * 1.5 * 1.001, w * .7) + (a, b), hs=.75 if (i + j) % 3 else 1.0) for i, j, a, b in zip(I2, J2, u2, v2)]
        out += _wrap(fr2, els2)
    return out


def _hammered(p, fr, lo, hi):
    a, b = fr.uv_box(lo, hi)
    dmin, dmax = fnum(p, 'ham_min'), max(fnum(p, 'ham_max'), fnum(p, 'ham_min'))
    mean = (dmin + dmax) / 2
    dens = max(.05, fnum(p, 'density'))
    rnd = max(0.0, min(1.0, fnum(p, 'randomness')))
    rng = np.random.default_rng(int(p.get('seed', 1)))
    cell = mean / max(dens, .05) * 1.0
    I, J = np.meshgrid(np.arange(int(math.floor(a[0] / cell)) - 1, int(math.ceil(b[0] / cell)) + 2),
                       np.arange(int(math.floor(a[1] / cell)) - 1, int(math.ceil(b[1] / cell)) + 2), indexing='ij')
    n = I.size
    centres = np.c_[(I.ravel() + .5) * cell, (J.ravel() + .5) * cell] + (rng.random((n, 2)) - .5) * cell * rnd * .9
    dia = dmin + rng.random(n) * (dmax - dmin)
    dep = rng.random(n)
    centres_f = centres
    els = []
    # elementy nie nakładają się: średnica ≤ odległość do najbliższego sąsiada (siatkowo ograniczona do komórki)
    cap = cell * (1 + (1 - rnd) * .0) * 1.0
    for q, d, t in zip(centres_f, dia, dep):
        d = min(d, cap * (1.15 if rnd < .5 else 1.0))
        els.append(El('dome', q, shape='cap', d=float(d), hs=float(fnum(p, 'ham_dmin') + t * (fnum(p, 'ham_dmax') - fnum(p, 'ham_dmin'))) / max(fnum(p, 'height'), 1e-3), hd=float(fnum(p, 'ham_dmin') + t * (fnum(p, 'ham_dmax') - fnum(p, 'ham_dmin'))) / max(fnum(p, 'depth'), 1e-3), extra='hammer'))
    return _wrap(fr, els)


def gen_triangles(p, fr, lo, hi):
    s = max(fnum(p, 'size'), .5)
    kind = p.get('tri_kind', 'equilateral')
    ratio = fnum(p, 'tri_ratio') if kind == 'scalene' else 1.0
    pit = pitch(p, s)
    wall = fnum(p, 'wall')
    dx, dy = pit[0] / 2, pit[1] * (math.sqrt(3) / 2) * ratio
    I, J, u, v = lattice(fr, lo, hi, dx, dy, 0.0)
    els = []
    for i, j, a, b in zip(I, J, u, v):
        up = (i + j) % 2 == 0
        # trójkąt o podstawie pit[0] i wysokości dy; środek ciężkości w (a, b)
        h = dy
        base = np.array([[-pit[0] / 2, -h / 3], [pit[0] / 2, -h / 3], [0.0, 2 * h / 3]])
        if not up:
            base = base * [1, -1]
            base = base[::-1]
        if wall > 0:
            q = inset(base, wall / 2)
            if len(q) < 3:
                continue
        else:
            q = base
        if p.get('fill') == 'outline':
            inn = inset(base, wall / 2 + max(wall, .2))
            if len(inn) < 3:
                continue
            els.append(El('poly', (a, b), poly=q + (a, b), holes=[inn + (a, b)]))
        else:
            els.append(El('poly', (a, b), poly=q + (a, b), sign=1 if (not p.get('alternate', True) or up) else -1))
    return _wrap(fr, els)


def gen_custom(p, fr, lo, hi):
    """Własny wzór: kontury (szkic / SVG / DXF) powielane w układzie prostokątnym, promieniowym, naprzemiennym albo losowym;
    albo istniejąca bryła jako element (kształt przenoszony na powierzchnię przez silnik)."""
    loops = p.get('custom_loops')
    solid = p.get('custom_src') == 'solid'
    if not solid and not loops:
        raise kernel.CadError('Własny wzór: wskaż szkic z zamkniętymi konturami albo wczytaj plik SVG / DXF.')
    sc = max(.01, fnum(p, 'c_scale'))
    rt = math.radians(fnum(p, 'c_rot'))
    if solid:
        ext = max(fnum(p, 'size'), .3)
        proto = None
    else:
        L = [np.asarray(q, float) for q in loops]
        allp = np.vstack(L)
        cen = (allp.min(0) + allp.max(0)) / 2
        proto = [(q - cen) @ rot(rt).T * sc for q in L]
        ext = float(np.ptp(np.vstack(proto), axis=0).max())
    pit = pitch(p, ext * 1.3)
    lay = p.get('c_layout', 'rect')
    pos = []
    if lay == 'radial':
        a, b = fr.uv_box(lo, hi)
        c = (a + b) / 2
        n = max(1, int(fnum(p, 'c_count')))
        rad = pit[0] * 1.0
        for r_i in range(0, int(float(np.linalg.norm(b - a)) / 2 / max(rad, .1)) + 1):
            k = n * max(1, r_i)
            for m in range(k if r_i else 1):
                t = 2 * math.pi * m / k
                pos.append((c + r_i * rad * np.array([math.cos(t), math.sin(t)]), t))
    elif lay == 'random':
        a, b = fr.uv_box(lo, hi)
        rng = np.random.default_rng(int(p.get('seed', 1)))
        nn = min(int(np.prod(b - a) / (pit[0] * pit[1]) * .6) + 1, 100000)
        Q = _poisson_filter(a + rng.random((nn, 2)) * (b - a), ext * 1.1)
        pos = [(q, rng.random() * 2 * math.pi * fnum(p, 'randomness')) for q in Q]
    else:
        I, J, u, v = lattice(fr, lo, hi, pit[0], pit[1], 50.0 if lay == 'stagger' else 0.0)
        pos = [(np.array([a, b]), 0.0) for a, b in zip(u, v)]
    els = []
    for q, t in pos:
        if solid:
            els.append(El('solid', q, d=ext, ang=t, extra=dict(body=p.get('custom_body'))))
            continue
        R = rot(t)
        shapes = [s @ R.T + q for s in proto]
        # kontury zagnieżdżone: parzystość (kontur w konturze = otwór)
        outers, holes = [], []
        for i, s in enumerate(shapes):
            depth = sum(1 for j, o in enumerate(shapes) if j != i and _inside(s.mean(0), o))
            (holes if depth % 2 else outers).append(s)
        for o in outers:
            hs = [h for h in holes if _inside(h.mean(0), o)]
            els.append(El('poly', o.mean(0), poly=o, holes=hs))
    return _wrap(fr, els)


def _inside(pt, poly):
    x, y = pt
    c = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi, xj, yj = poly[i][0], poly[i][1], poly[j][0], poly[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-18) + xi:
            c = not c
        j = i
    return c


GENERATORS = {'knurl_cross': gen_knurl_cross, 'knurl_straight': gen_knurl_straight, 'knurl_spiral': gen_knurl_spiral, 'honeycomb': gen_honeycomb,
              'dots': gen_dots, 'pyramids': gen_pyramids, 'waves': gen_waves, 'voronoi': gen_voronoi, 'checker': gen_checker,
              'image': gen_waves, 'herringbone': gen_herringbone, 'scales': gen_scales, 'weave': gen_weave, 'hammered': _hammered, 'triangles': gen_triangles,
              'custom': gen_custom}


def generate(p, frame, lo, hi):
    """Elementy wzoru dla prostokąta lo-hi w dziedzinie. Pierścienie liczone wokół własnego środka (poza układem wzoru)."""
    pat = p.get('pattern', 'knurl_cross')
    if pat == 'rings':
        return gen_rings(p, frame, lo, hi)
    gen = GENERATORS.get(pat)
    if gen is None:
        raise kernel.CadError(f'Nieznany wzór tekstury: {pat}.')
    return gen(p, frame, lo, hi)
