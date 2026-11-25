"""Generator obudów - etap 1: elementy źródłowe, układ współrzędnych i przestrzeń zajmowana przez elementy.

Struktura danych (EnclosureSpec) jest zapisywana w kroku historii 'enclosure' i w obiekcie-definicji obudowy (rodzaj
'encl', pozycja „Obudowy” na liście Obiekty). Dalsze etapy dopisują swoje parametry do tych samych pól
(clearance, walls, split, mounts, openings, vents, closure, process) - przepis jest wersjonowany, więc starsze projekty
dalej się wczytują.

Geometria:
- wspólna ramka (AABB) - BRepBndLib.AddOptimal + Bnd_Box (dokładna, bez tolerancji kształtu),
- zorientowana ramka (OBB) - BRepBndLib.AddOBB + Bnd_OBB (oś Z tej, która najbliżej globalnego Z, X - dłuższa z pozostałych),
- ramka w układzie ściany - bryły przenoszone transformacją gp_Trsf do układu ściany (Z = normalna na zewnątrz,
  X = kierunek najdłuższej prostej krawędzi ściany), potem AABB w tym układzie.
Kształty brył w dokumencie mają już zastosowane wszystkie przesunięcia i obroty (TopLoc_Location), a BRepBndLib je
uwzględnia - ramka odpowiada rzeczywistemu położeniu elementów."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import copy

import numpy as np

from . import kernel

SPEC_VERSION = 2               # 1 - definicja (etap 1); 2 - prostokątna obudowa jako bryła (etap 2)
FRAME_MODES = ('global', 'local', 'face')
FRAME_LABELS = {'global': 'Globalny (osie X, Y, Z)', 'local': 'Lokalny (dopasowany do elementów)', 'face': 'Ze ściany (wskazana ściana)'}
SOURCE_KINDS = ('solid', 'mesh')
MODES = ('open', 'closed', 'solid')
MODE_LABELS = {'open': 'Otwarta (bez górnej ścianki)', 'closed': 'Całkowicie zamknięta', 'solid': 'Pełna bryła zewnętrzna'}
SIDES = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')                # odstępy od elementów
WALLS = ('x-', 'x+', 'y-', 'y+', 'bottom', 'top')            # ścianki: cztery boczne, dno (Z-), górna (Z+)
SIDE_LABELS = {'x-': 'X−', 'x+': 'X+', 'y-': 'Y−', 'y+': 'Y+', 'z-': 'Z−', 'z+': 'Z+', 'bottom': 'Dno', 'top': 'Góra'}
DEFAULT_CLEARANCE = 2.0
DEFAULT_WALL = 2.0
MIN_WALL = 0.2                 # cieńsza ścianka nie daje sensownej bryły (i jest niewykonalna)
MAX_VALUE = 10000.0


@dataclass
class SourceRef:
    """Element źródłowy: trwały identyfikator obiektu dokumentu (Body.id) - bryły nie są zmieniane ani usuwane."""
    id: str
    name: str = ''
    kind: str = 'solid'
    source: str = ''          # 'step' / 'stl' / '' - skąd pochodzi obiekt (import)


@dataclass
class FrameSpec:
    """Układ współrzędnych obudowy: mode 'global' | 'local' | 'face'. Dla 'face' - ściana: id bryły, punkt na ścianie
    i normalna (ściana odnajdywana ponownie po punkcie, także po przeliczeniu historii)."""
    mode: str = 'global'
    face: dict | None = None


@dataclass
class Envelope:
    """Przestrzeń zajmowana przez elementy: środek, osie (wiersze: X, Y, Z) i wymiary wzdłuż osi (mm)."""
    center: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    axes: list = field(default_factory=lambda: [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    size: list = field(default_factory=lambda: [0.0, 0.0, 0.0])

    def corners(self):
        c = np.asarray(self.center, float)
        ax = np.asarray(self.axes, float)
        h = np.asarray(self.size, float) / 2
        return [c + sx * h[0] * ax[0] + sy * h[1] * ax[1] + sz * h[2] * ax[2]
                for sz in (-1, 1) for sy in (-1, 1) for sx in (-1, 1)]


@dataclass
class EnclosureSpec:
    """Definicja obudowy. Etap 1 wypełnia sources, frame i envelope; pozostałe grupy parametrów są miejscem na kolejne
    etapy (odstępy w sześciu kierunkach, ścianki, podział, mocowania, otwory, wentylacja, zamknięcie, technologia)."""
    version: int = SPEC_VERSION
    units: str = 'mm'
    sources: list = field(default_factory=list)          # [SourceRef]
    frame: FrameSpec = field(default_factory=FrameSpec)
    envelope: Envelope = field(default_factory=Envelope)
    shape: str = 'box'                                    # kształt obudowy (kolejne etapy: zaokrąglona, walec, pulpit, kontur)
    mode: str = 'closed'                                  # 'open' | 'closed' | 'solid'
    clearance: dict = field(default_factory=dict)         # odstępy od elementów: x-, x+, y-, y+, z-, z+ (+ 'linked')
    walls: dict = field(default_factory=dict)             # grubości: x-, x+, y-, y+, bottom, top (+ 'linked')
    split: dict = field(default_factory=dict)             # podział obudowy
    mounts: list = field(default_factory=list)            # mocowania
    openings: list = field(default_factory=list)          # otwory na złącza, wyświetlacze, przyciski
    vents: list = field(default_factory=list)             # wentylacja
    closure: dict = field(default_factory=dict)           # system zamykania
    process: dict = field(default_factory=dict)           # druk 3D / CNC / blacha / laser

    def to_json(self):
        return asdict(self)

    @staticmethod
    def from_json(data):
        data = copy.deepcopy(data or {})
        spec = EnclosureSpec()
        spec.version = int(data.get('version', 1))
        spec.units = data.get('units', 'mm')
        spec.sources = [SourceRef(**{k: v for k, v in s.items() if k in ('id', 'name', 'kind', 'source')}) for s in data.get('sources', [])]
        fr = data.get('frame') or {}
        spec.frame = FrameSpec(mode=fr.get('mode', 'global') if fr.get('mode') in FRAME_MODES else 'global', face=fr.get('face'))
        env = data.get('envelope') or {}
        spec.envelope = Envelope(center=list(env.get('center', [0, 0, 0])), axes=[list(a) for a in env.get('axes', Envelope().axes)],
                                 size=list(env.get('size', [0, 0, 0])))
        for key in ('shape', 'mode', 'clearance', 'walls', 'split', 'mounts', 'openings', 'vents', 'closure', 'process'):
            if key in data:
                setattr(spec, key, data[key])
        return spec


# ---------------------------------------------------------------------------------------------- ramki
def _union(shapes):
    shapes = [s for s in shapes if s is not None]
    if not shapes:
        raise kernel.CadError('Wybierz co najmniej jedną bryłę.')
    return shapes[0] if len(shapes) == 1 else kernel.compound(shapes)


def _check(size):
    size = np.asarray(size, float)
    if not np.all(np.isfinite(size)) or float(size.max(initial=0.0)) <= 1e-9:
        raise kernel.CadError('Nie udało się wyznaczyć przestrzeni zajmowanej przez elementy (puste albo uszkodzone bryły).')
    return size


def aabb(shapes):
    """Wspólna ramka w osiach globalnych (Bnd_Box, BRepBndLib.AddOptimal - dokładna, bez tolerancji kształtu)."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    for s in shapes:
        BRepBndLib.AddOptimal_s(s.wrapped, box, True, False)
    if box.IsVoid():
        raise kernel.CadError('Wybrane elementy nie mają geometrii.')
    x0, y0, z0, x1, y1, z1 = box.Get()
    lo, hi = np.array([x0, y0, z0]), np.array([x1, y1, z1])
    size = _check(hi - lo)
    return Envelope(center=list(map(float, (lo + hi) / 2)), axes=[[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]], size=list(map(float, size)))


def obb(shapes):
    """Zorientowana ramka (Bnd_OBB, BRepBndLib.AddOBB). Osie porządkowane: Z - najbliżej globalnego Z (obudowa stoi),
    X - dłuższa z pozostałych; układ prawoskrętny."""
    from OCP.Bnd import Bnd_OBB
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_OBB()
    BRepBndLib.AddOBB_s(_union(shapes).wrapped, box, True, True, False)
    if box.IsVoid():
        raise kernel.CadError('Wybrane elementy nie mają geometrii.')
    xyz = lambda v: np.array([v.X(), v.Y(), v.Z()], float)
    axes = [xyz(box.XDirection()), xyz(box.YDirection()), xyz(box.ZDirection())]
    half = [box.XHSize(), box.YHSize(), box.ZHSize()]
    k = int(np.argmax([abs(a[2]) for a in axes]))
    z, hz = axes[k], half[k]
    if z[2] < 0:
        z = -z
    rest = [(half[i], axes[i]) for i in range(3) if i != k]
    rest.sort(key=lambda item: -item[0])
    (hx, x), (hy, _) = rest
    if x @ np.array([1.0, 0, 0]) < 0 and abs(x[0]) > 1e-9:
        x = -x
    y = np.cross(z, x)
    size = _check(2 * np.array([hx, hy, hz]))
    return Envelope(center=list(map(float, xyz(box.Center()))), axes=[list(map(float, x)), list(map(float, y)), list(map(float, z))],
                    size=list(map(float, size)))


def face_frame(shape, point):
    """Układ ściany: (początek, X, Y, Z). Z - normalna ściany na zewnątrz bryły, X - najdłuższa prosta krawędź ściany
    (albo oś ściany walcowej / dowolna prostopadła), początek - punkt na ścianie."""
    index, face = kernel.face_at_point(shape, point, tol=.05)
    if face is None:
        raise kernel.CadError('Nie znaleziono wskazanej ściany.')
    if not kernel.is_planar_face(face):
        raise kernel.CadError('Ściana orientacji musi być płaska.')
    p = np.asarray(point, float)
    n = np.array(face.normalAt(face.Center()).toTuple(), float)
    n = n / max(np.linalg.norm(n), 1e-12)
    lines = [e for e in face.Edges() if e.geomType() == 'LINE']
    if lines:
        e = max(lines, key=lambda e: e.Length())
        x = np.array(e.endPoint().toTuple(), float) - np.array(e.startPoint().toTuple(), float)
    else:
        x = np.cross(n, (0, 0, 1.0) if abs(n[2]) < .9 else (1.0, 0, 0))
    x = x - (x @ n) * n
    x = x / max(np.linalg.norm(x), 1e-12)
    y = np.cross(n, x)
    return p, x, y, n


def framed_box(shapes, origin, x, y, z):
    """Ramka w zadanym układzie: bryły przeniesione transformacją do układu (gp_Trsf), dokładny AABB, powrót do świata."""
    rot = np.vstack([x, y, z])                       # świat -> układ
    moved = [kernel.transformed(s, rot, -rot @ np.asarray(origin, float)) for s in shapes]
    local = aabb(moved)
    c = np.asarray(origin, float) + rot.T @ np.asarray(local.center, float)
    return Envelope(center=list(map(float, c)), axes=[list(map(float, x)), list(map(float, y)), list(map(float, z))], size=local.size)


def envelope(bodies, spec):
    """Przestrzeń zajmowana przez elementy źródłowe spec w podanym stanie dokumentu (bodies)."""
    by_id = {b.id: b for b in bodies}
    shapes = []
    missing = []
    for src in spec.sources:
        body = by_id.get(src.id)
        if body is None:
            missing.append(src.name or src.id)
            continue
        shapes.append(body.shape)
    if not shapes:
        raise kernel.CadError('Elementów źródłowych obudowy już nie ma.' if missing else 'Wybierz co najmniej jedną bryłę.')
    mode = spec.frame.mode
    if mode == 'local':
        return obb(shapes)
    if mode == 'face':
        face = spec.frame.face or {}
        owner = by_id.get(face.get('id'))
        if owner is None:
            raise kernel.CadError('Bryły ze ścianą orientacji już nie ma.')
        origin, x, y, z = face_frame(owner.shape, face['point'])
        return framed_box(shapes, origin, x, y, z)
    return aabb(shapes)


def envelope_shape(env, solid=True):
    """Kształt przestrzeni: bryła prostopadłościanu (podgląd) albo jego krawędzie (definicja obudowy w dokumencie)."""
    import cadquery as cq
    size = np.maximum(np.asarray(env.size, float), 1e-3)
    ax = np.asarray(env.axes, float)
    box = cq.Solid.makeBox(*map(float, size), pnt=cq.Vector(*map(float, -size / 2)))
    shape = kernel.transformed(box, ax.T, np.asarray(env.center, float))
    if solid:
        if not shape.isValid():
            raise kernel.CadError('Niepoprawna bryła podglądu.')
        return shape
    return kernel.compound(shape.Edges())


def dimension_items(env, prefix='enc'):
    """Linie wymiarów X, Y, Z wzdłuż krawędzi przestrzeni (dla nakładki wymiarów widoku)."""
    c = np.asarray(env.center, float)
    ax = np.asarray(env.axes, float)
    h = np.asarray(env.size, float) / 2
    base = c - h[0] * ax[0] - h[1] * ax[1] - h[2] * ax[2]
    out = []
    for i, name in enumerate('XYZ'):
        a = base
        b = base + ax[i] * 2 * h[i]
        out.append(dict(id=f'{prefix}:{name}', a=a, b=b, axis=None, value=float(2 * h[i]), sym=False, selected=False, label=name))
    return out


# ---------------------------------------------------------------------------------------------- etap 2: prostokątna obudowa
def clearance_of(spec):
    c = spec.clearance or {}
    return {k: float(c.get(k, DEFAULT_CLEARANCE)) for k in SIDES}


def walls_of(spec):
    w = spec.walls or {}
    return {k: float(w.get(k, DEFAULT_WALL)) for k in WALLS}


def box_layout(env, spec):
    """Prostopadłościany obudowy w układzie przestrzeni (środek przestrzeni = 0): dict(inner=(lo, hi), outer=(lo, hi),
    inner_size, outer_size). Wnętrze = przestrzeń elementów + odstępy; zewnętrze = wnętrze + grubości ścianek (obudowa
    otwarta nie ma górnej ścianki). Wartości niepozwalające na poprawną bryłę -> CadError (z opisem)."""
    c, w = clearance_of(spec), walls_of(spec)
    for key, value in c.items():
        if not np.isfinite(value) or value < 0 or value > MAX_VALUE:
            raise kernel.CadError(f'Odstęp {SIDE_LABELS[key]} musi być od 0 do {MAX_VALUE:g} mm.')
    for key, value in w.items():
        if spec.mode == 'open' and key == 'top':
            continue
        if not np.isfinite(value) or value < MIN_WALL or value > MAX_VALUE:
            raise kernel.CadError(f'Grubość ścianki {SIDE_LABELS[key]} musi być od {MIN_WALL:g} do {MAX_VALUE:g} mm.')
    if spec.mode not in MODES:
        raise kernel.CadError('Nieznany rodzaj obudowy.')
    half = np.asarray(env.size, float) / 2
    lo = -half - np.array([c['x-'], c['y-'], c['z-']])
    hi = half + np.array([c['x+'], c['y+'], c['z+']])
    inner = hi - lo
    if float(inner.min()) <= 1e-6:
        raise kernel.CadError('Wnętrze obudowy musi mieć dodatnie wymiary.')
    top = 0.0 if spec.mode == 'open' else w['top']
    olo = lo - np.array([w['x-'], w['y-'], w['bottom']])
    ohi = hi + np.array([w['x+'], w['y+'], top])
    return dict(inner=(lo, hi), outer=(olo, ohi), inner_size=inner, outer_size=ohi - olo)


def _make_box(lo, hi):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    maker = BRepPrimAPI_MakeBox(gp_Pnt(*map(float, lo)), gp_Pnt(*map(float, hi)))
    maker.Build()
    if not maker.IsDone():
        raise kernel.CadError('Nie udało się utworzyć prostopadłościanu obudowy.')
    return maker.Shape()


def check_solid(shape):
    """BRepCheck_Analyzer + bryła o dodatniej objętości - inaczej CadError."""
    from OCP.BRepCheck import BRepCheck_Analyzer
    import cadquery as cq
    if shape is None or shape.IsNull():
        raise kernel.CadError('Obudowa nie powstała.')
    if not BRepCheck_Analyzer(shape).IsValid():
        raise kernel.CadError('Obudowa ma niepoprawną geometrię (BRepCheck).')
    out = cq.Shape.cast(shape)
    if not out.Solids() or float(out.Volume()) <= 1e-9:
        raise kernel.CadError('Obudowa nie jest bryłą.')
    return out


def box_enclosure(env, spec):
    """Prostokątna obudowa jako bryła B-Rep: zewnętrzny prostopadłościan (BRepPrimAPI_MakeBox) minus wnętrze
    (BRepAlgoAPI_Cut); obudowa otwarta - wnętrze wychodzi ponad górną krawędź; pełna bryła - sam zewnętrzny. Geometria
    elementów nie jest odejmowana. Wynik w położeniu przestrzeni (osie i środek z envelope)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    lay = box_layout(env, spec)
    outer = _make_box(*lay['outer'])
    if spec.mode == 'solid':
        local = outer
    else:
        lo, hi = lay['inner']
        if spec.mode == 'open':
            hi = hi + np.array([0.0, 0.0, 1.0 + float(lay['outer_size'][2])])        # wnętrze przechodzi przez górę
        cut = BRepAlgoAPI_Cut(outer, _make_box(lo, hi))
        cut.Build()
        if not cut.IsDone():
            raise kernel.CadError('Wycięcie wnętrza obudowy nie powiodło się.')
        local = cut.Shape()
    import cadquery as cq
    shape = kernel.transformed(cq.Shape.cast(local), np.asarray(env.axes, float).T, np.asarray(env.center, float))
    return check_solid(shape.wrapped)


def outer_dimension_items(env, spec, prefix='enc'):
    """Wymiary zewnętrzne X / Y / Z wzdłuż krawędzi obudowy (nakładka wymiarów widoku)."""
    lay = box_layout(env, spec)
    lo, hi = lay['outer']
    c = np.asarray(env.center, float)
    ax = np.asarray(env.axes, float)
    world = lambda p: c + ax.T @ np.asarray(p, float)
    out = []
    for i, name in enumerate('XYZ'):
        b = np.array(lo, float)
        b[i] = hi[i]
        out.append(dict(id=f'{prefix}:{name}', a=world(lo), b=world(b), axis=None, value=float(hi[i] - lo[i]), sym=False, selected=False, label=name))
    return out


def run(bodies, recipe):
    """Krok historii 'enclosure': definicja obudowy (obiekt 'encl' z krawędziami przestrzeni i przepisem w meta).
    Przy przeliczaniu przestrzeń liczy się od nowa z aktualnego położenia elementów źródłowych."""
    from dataclasses import replace
    from .document import Body
    spec = EnclosureSpec.from_json(recipe['spec'])
    env = envelope(bodies, spec)
    spec.envelope = env
    ident = recipe['out']
    name = recipe.get('name') or 'Obudowa'
    meta = dict(enclosure=spec.to_json())
    old = next((b for b in bodies if b.id == ident), None)
    if spec.version >= 2:              # etap 2: prostokątna obudowa jako bryła (nowy element dokumentu)
        shape = box_enclosure(env, spec)
        body = (replace(old, shape=shape, meta=meta, mesh=None) if old is not None
                else Body(name, shape, 'solid', 'XY', id=ident, meta=meta)).prepared()
    else:                              # definicja z etapu 1 (starsze projekty)
        shape = envelope_shape(env, solid=False)
        body = (replace(old, shape=shape, meta=meta, mesh=None) if old is not None
                else Body(name, shape, 'encl', 'XY', id=ident, meta=meta)).prepared()
    return [body if b.id == ident else b for b in bodies] if old is not None else [*bodies, body]
