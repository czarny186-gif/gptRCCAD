"""Parametry koła walcowego, wymiary pochodne i walidacja (bez Qt, bez Open CASCADE).

Oznaczenia (ISO 21771 / PN-ISO 53, zarys odniesienia: wysokość głowy 1·m, wysokość stopy 1,25·m):
  m   moduł normalny [mm]            z   liczba zębów (dla koła wewnętrznego dodatnia)
  α   kąt przyporu normalny [°]      β   kąt pochylenia linii zęba [°] (0 = zęby proste)
  b   szerokość wieńca [mm]          x   współczynnik korekcji zarysu
  j   luz międzyzębny pary [mm] (normalny, po obwodzie) - każde koło pary pocienia ząb o j/2

Korekcja x: dodatnia odsuwa zarys od środka koła o x·m (koło i okrąg głów oraz stóp przesuwają się na zewnątrz).
Przy kole zewnętrznym ząb robi się grubszy, przy kole wewnętrznym - wręby szersze, a zęby cieńsze.

Koło zewnętrzne: średnica otworu (0 = bez otworu) i opcjonalna piasta.
Koło wewnętrzne (wieniec): zamiast otworu średnica zewnętrzna wieńca (0 = dobrana sama); piasty nie ma."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields

KINDS = ('spur_ext', 'helical_ext', 'spur_int', 'helical_int')
KIND_TITLES = {'spur_ext': 'Proste zewnętrzne', 'helical_ext': 'Skośne zewnętrzne',
               'spur_int': 'Proste wewnętrzne', 'helical_int': 'Skośne wewnętrzne'}
HANDS = ('right', 'left')

HA, HF = 1.0, 1.25        # wysokość głowy i stopy zarysu odniesienia (w modułach)

# granice pól: (najmniej, najwięcej) - poza nimi błąd
LIMITS = dict(module=(.05, 100.0), teeth=(5, 1000), pressure=(10.0, 35.0), helix=(.5, 45.0), width=(.01, 1e4),
              shift=(-1.0, 1.5), backlash=(0.0, None), bore=(0.0, 1e5), hub_diameter=(0.0, 1e5), hub_length=(0.0, 1e4),
              rim_diameter=(0.0, 1e5))


@dataclass
class GearParams:
    kind: str = 'spur_ext'
    module: float = 2.0
    teeth: int = 20
    pressure: float = 20.0
    helix: float = 15.0          # używany tylko przy zębach skośnych
    hand: str = 'right'          # kierunek linii zęba (skośne)
    width: float = 10.0
    shift: float = 0.0
    backlash: float = 0.1
    bore: float = 0.0            # koło zewnętrzne: średnica otworu, 0 = bez otworu
    hub: bool = False            # koło zewnętrzne: piasta
    hub_diameter: float = 0.0
    hub_length: float = 0.0      # wysunięcie piasty poza wieniec
    rim_diameter: float = 0.0    # koło wewnętrzne: średnica zewnętrzna wieńca, 0 = dobrana sama

    @property
    def internal(self):
        return self.kind.endswith('_int')

    @property
    def helical(self):
        return self.kind.startswith('helical')

    @property
    def beta(self):
        """Kąt pochylenia w stopniach - 0 dla zębów prostych, niezależnie od zapamiętanej wartości pola."""
        return float(self.helix) if self.helical else 0.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        names = {f.name for f in fields(cls)}
        values = {k: v for k, v in dict(data or {}).items() if k in names}
        params = cls(**values)
        params.teeth = int(round(params.teeth))
        params.hub = bool(params.hub)
        return params


@dataclass
class Check:
    level: str        # 'error' albo 'warning'
    field: str        # nazwa pola GearParams, którego dotyczy ('' = ogólne)
    message: str


def inv(angle):
    """Funkcja ewolwentowa inv(α) = tg α - α (α w radianach)."""
    return math.tan(angle) - angle


def derived(p: GearParams):
    """Wymiary pochodne koła (mm, kąty w stopniach). Nie sprawdza poprawności - patrz validate()."""
    m, z, x = float(p.module), int(p.teeth), float(p.shift)
    beta = math.radians(p.beta)
    alpha_n = math.radians(float(p.pressure))
    mt = m / math.cos(beta)
    alpha_t = math.atan(math.tan(alpha_n) / math.cos(beta))
    d = z * mt
    db = d * math.cos(alpha_t)
    if p.internal:
        da = d - 2 * m * (HA - x)              # głowy zębów wewnętrznych - mniejsza średnica
        df = d + 2 * m * (HF + x)              # stopy - większa średnica
    else:
        da = d + 2 * m * (HA + x)
        df = d - 2 * m * (HF - x)
    # grubość zęba na średnicy podziałowej (po obwodzie, czołowa), pocieniona o połowę luzu pary
    sign = -1 if p.internal else 1
    s_n = m * (math.pi / 2 + sign * 2 * x * math.tan(alpha_n)) - float(p.backlash) / 2
    s_t = s_n / math.cos(beta)
    # grubość zęba na średnicy głów (zaostrzenie zęba)
    s_a = None
    if da > db > 0:
        alpha_a = math.acos(db / da)
        if p.internal:
            s_a = da * (s_t / d - inv(alpha_t) + inv(alpha_a))
        else:
            s_a = da * (s_t / d + inv(alpha_t) - inv(alpha_a))
    # podcięcie stopy (koło zewnętrzne): zastępcza liczba zębów i liczba graniczna
    z_v = z / math.cos(beta) ** 3
    z_min = 2 * (HA - x) / math.sin(alpha_n) ** 2 * 5 / 6      # praktyczna granica podcięcia (DIN 3960: 5/6 granicy teoretycznej)
    rim = float(p.rim_diameter)
    if p.internal and rim <= 0:
        rim = df + 2 * 2.5 * m                 # wieniec dobrany sam: 2,5 modułu materiału pod stopami
    return dict(mt=mt, alpha_t=math.degrees(alpha_t), d=d, db=db, da=da, df=df, pitch=math.pi * m,
                height=abs(da - df) / 2, s=s_t, s_a=s_a, z_v=z_v, z_min=z_min, rim=rim,
                lead=(math.pi * d / math.tan(beta)) if beta else None)


def _limit(checks, name, value, title, unit=''):
    low, high = LIMITS[name]
    if low is not None and value < low - 1e-12:
        checks.append(Check('error', name, f'{title}: najmniej {low:g}{unit}.'))
        return False
    if high is not None and value > high + 1e-12:
        checks.append(Check('error', name, f'{title}: najwięcej {high:g}{unit}.'))
        return False
    return True


def validate(p: GearParams):
    """Lista uwag (Check). Błąd ('error') blokuje generowanie koła, ostrzeżenie ('warning') nie."""
    checks = []
    if p.kind not in KINDS:
        return [Check('error', 'kind', 'Nieznany rodzaj uzębienia.')]
    if p.helical and p.hand not in HANDS:
        checks.append(Check('error', 'hand', 'Kierunek skrętu: prawy albo lewy.'))
    if not float(p.teeth).is_integer():
        checks.append(Check('error', 'teeth', 'Liczba zębów musi być liczbą całkowitą.'))
    ok = all([_limit(checks, 'module', p.module, 'Moduł', ' mm'),
              _limit(checks, 'teeth', p.teeth, 'Liczba zębów'),
              _limit(checks, 'pressure', p.pressure, 'Kąt przyporu', '°'),
              _limit(checks, 'helix', p.helix, 'Kąt pochylenia', '°') if p.helical else True,
              _limit(checks, 'width', p.width, 'Szerokość koła', ' mm'),
              _limit(checks, 'shift', p.shift, 'Korekcja zarysu'),
              _limit(checks, 'backlash', p.backlash, 'Luz międzyzębny', ' mm')])
    if not ok:
        return checks              # dalsze wymiary nie mają sensu przy wartościach spoza zakresu
    m = float(p.module)
    if p.backlash > .5 * m:
        checks.append(Check('error', 'backlash', f'Luz międzyzębny za duży: najwięcej połowa modułu ({.5 * m:g} mm).'))
        return checks
    if p.backlash > .15 * m:
        checks.append(Check('warning', 'backlash', 'Duży luz międzyzębny (powyżej 0,15·m) - przekładnia będzie wyraźnie luźna.'))
    g = derived(p)
    if p.internal:
        if g['da'] <= g['db'] + 1e-9:
            checks.append(Check('error', 'teeth', 'Za mało zębów koła wewnętrznego: głowy zębów wypadają w okręgu zasadniczym '
                                                  '(brak ewolwenty). Zwiększ liczbę zębów albo korekcję zarysu.'))
    elif g['z_v'] < g['z_min'] - 1e-9:
        checks.append(Check('warning', 'teeth', f'Podcięcie stopy zęba: przy tej korekcji potrzeba co najmniej {math.ceil(g["z_min"] - 1e-9)} zębów '
                                                f'(zastępcza liczba {g["z_v"]:.1f}). Zwiększ korekcję zarysu albo liczbę zębów.'))
    if g['s'] <= 0:
        checks.append(Check('error', 'backlash', 'Ząb nie ma grubości - zmniejsz luz albo korekcję zarysu.'))
    elif g['s_a'] is not None and g['s_a'] <= 0:
        checks.append(Check('error', 'shift', 'Ząb zaostrzony: grubość na wierzchołku wychodzi ujemna. Zmniejsz korekcję zarysu.'))
    elif g['s_a'] is not None and g['s_a'] < .25 * m:
        checks.append(Check('warning', 'shift', f'Ząb prawie zaostrzony: grubość na wierzchołku {g["s_a"]:.2f} mm (zalecane co najmniej 0,25·m).'))
    if g['df'] <= 0:
        checks.append(Check('error', 'teeth', 'Średnica stóp wychodzi ujemna - za mało zębów przy tej korekcji.'))
        return checks
    if p.internal:
        if not _limit(checks, 'rim_diameter', p.rim_diameter, 'Średnica wieńca', ' mm'):
            return checks
        wall = (g['rim'] - g['df']) / 2
        if wall < m - 1e-9:
            checks.append(Check('error', 'rim_diameter', f'Wieniec za cienki pod stopami zębów: średnica zewnętrzna co najmniej {g["df"] + 2 * m:.2f} mm.'))
        elif wall < 2.5 * m - 1e-9:
            checks.append(Check('warning', 'rim_diameter', 'Cienki wieniec pod stopami zębów (mniej niż 2,5·m).'))
        return checks
    if not _limit(checks, 'bore', p.bore, 'Średnica otworu', ' mm'):
        return checks
    if p.bore > 0:
        wall = (g['df'] - p.bore) / 2
        if wall < m - 1e-9:
            checks.append(Check('error', 'bore', f'Otwór za duży: wieniec pod zębami cieńszy niż moduł. Najwięcej {max(g["df"] - 2 * m, 0):.2f} mm.'))
        elif wall < 2.5 * m - 1e-9:
            checks.append(Check('warning', 'bore', 'Cienki wieniec między otworem a stopami zębów (mniej niż 2,5·m).'))
    if p.hub:
        if not (_limit(checks, 'hub_diameter', p.hub_diameter, 'Średnica piasty', ' mm') and
                _limit(checks, 'hub_length', p.hub_length, 'Długość piasty', ' mm')):
            return checks
        if p.hub_length <= 0:
            checks.append(Check('error', 'hub_length', 'Długość piasty musi być większa od zera.'))
        if p.hub_diameter <= p.bore + 1e-9:
            checks.append(Check('error', 'hub_diameter', 'Piasta musi być szersza niż otwór.'))
        elif p.hub_diameter > g['df'] + 1e-9:
            checks.append(Check('warning', 'hub_diameter', 'Piasta szersza niż średnica stóp zębów - zasłoni część uzębienia.'))
    return checks
