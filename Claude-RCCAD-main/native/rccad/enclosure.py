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

SPEC_VERSION = 3               # 1 - definicja (etap 1); 2 - prostokątna obudowa jako bryła (etap 2); 3 - podział (etap 4)
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
AXIS_OF = {'x-': (0, -1), 'x+': (0, 1), 'y-': (1, -1), 'y+': (1, 1), 'z-': (2, -1), 'z+': (2, 1)}
OPPOSITE = {'x-': 'x+', 'x+': 'x-', 'y-': 'y+', 'y+': 'y-', 'z-': 'z+', 'z+': 'z-'}
WALL_OF = {'x-': 'x-', 'x+': 'x+', 'y-': 'y-', 'y+': 'y+', 'z-': 'bottom', 'z+': 'top'}
# etap 4: podział na podstawę i pokrywę
SPLIT_MODES = ('x', 'y', 'z', 'plane', 'face')
SPLIT_LABELS = {'x': 'Wzdłuż osi X', 'y': 'Wzdłuż osi Y', 'z': 'Wzdłuż osi Z', 'plane': 'Według wskazanej płaszczyzny',
                'face': 'Według płaskiej ściany elementu'}
PLANES = ('XY', 'XZ', 'YZ')
JOINTS = ('flat', 'lap_in', 'lap_out', 'tongue')
JOINT_LABELS = {'flat': 'Płaskie powierzchnie styku', 'lap_in': 'Zakładka wewnętrzna', 'lap_out': 'Zakładka zewnętrzna',
                'tongue': 'Pióro i wpust'}
SPLIT_DEFAULTS = dict(enabled=False, mode='z', plane='XY', face=None, unit='%', position=70.0, joint='flat',
                      width=1.0, height=2.0, depth=2.2, gap=0.2)


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
    local, _lay = local_enclosure(env, spec)
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


def run(bodies, recipe, check_sources=False):
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
    if spec.version >= 2 and split_of(spec)['enabled']:       # etap 4: podstawa i pokrywa - dwie osobne bryły w grupie obudowy
        parts = split_enclosure(env, spec, bodies, check_sources=check_sources)
        lid_id = recipe.get('out_lid') or ident + '-lid'
        folder = recipe.get('folder') or name
        out = list(bodies)
        for pid, part, title in ((ident, 'base', 'podstawa'), (lid_id, 'lid', 'pokrywa')):
            prev = next((b for b in out if b.id == pid), None)
            pmeta = dict(enclosure=spec.to_json(), enclosure_part=part)
            made = (replace(prev, shape=parts[part], meta=pmeta, mesh=None) if prev is not None
                    else Body(f'{name} - {title}', parts[part], 'solid', 'XY', id=pid, meta=pmeta, folder=folder)).prepared()
            out = [made if b.id == pid else b for b in out] if prev is not None else [*out, made]
        return out
    if spec.version >= 2:              # etap 2: prostokątna obudowa jako bryła (nowy element dokumentu)
        shape = box_enclosure(env, spec)
        body = (replace(old, shape=shape, meta=meta, mesh=None) if old is not None
                else Body(name, shape, 'solid', 'XY', id=ident, meta=meta)).prepared()
    else:                              # definicja z etapu 1 (starsze projekty)
        shape = envelope_shape(env, solid=False)
        body = (replace(old, shape=shape, meta=meta, mesh=None) if old is not None
                else Body(name, shape, 'encl', 'XY', id=ident, meta=meta)).prepared()
    return [body if b.id == ident else b for b in bodies] if old is not None else [*bodies, body]


# ---------------------------------------------------------------------------------------------- etap 3: manipulatory i podgląd
def _world(env):
    c = np.asarray(env.center, float)
    ax = np.asarray(env.axes, float)
    return lambda p: c + ax.T @ np.asarray(p, float)


def box_mesh(lo, hi, env, top=True, edges=True, key0=0):
    """Siatka prostopadłościanu (lo, hi w układzie przestrzeni) bez geometrii OCC - szybki podgląd podczas przeciągania.
    top=False: bez górnej ściany (obudowa otwarta)."""
    world = _world(env)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    corner = lambda i: np.array([hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]])
    v = np.array([world(corner(i)) for i in range(8)], np.float32)
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]   # dół, góra, Y-, Y+, X-, X+
    tris = [t for n, q in enumerate(quads) if top or n != 1 for t in ((q[0], q[1], q[2]), (q[0], q[2], q[3]))]
    lines = {}
    if edges:
        for n, (a, b) in enumerate(((0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7))):
            lines[key0 + n] = v[[a, b]]
    return kernel.DisplayMesh(v, np.array(tris, np.uint32).reshape(-1, 3), lines, tuple(map(float, v.mean(axis=0))),
                              float(np.linalg.norm(v.max(axis=0) - v.min(axis=0))))


def merge_meshes(meshes):
    """Kilka siatek podglądu w jednej (jedna warstwa podglądu widoku)."""
    meshes = [m for m in meshes if m is not None]
    if not meshes:
        return None
    verts, tris, edges, base = [], [], {}, 0
    for n, m in enumerate(meshes):
        verts.append(np.asarray(m.vertices, np.float32))
        tris.append(np.asarray(m.triangles, np.int64).reshape(-1, 3) + base)
        base += len(m.vertices)
        for k, pts in m.edges.items():
            edges[(n, k)] = pts
    v = np.concatenate(verts) if verts else np.empty((0, 3), np.float32)
    t = np.concatenate(tris).astype(np.uint32) if tris else np.empty((0, 3), np.uint32)
    return kernel.DisplayMesh(v, t, edges, tuple(map(float, v.mean(axis=0))) if len(v) else (0.0, 0.0, 0.0),
                              max(m.size for m in meshes))


def moved_mesh(mesh, shift):
    shift = np.asarray(shift, np.float32)
    return kernel.DisplayMesh((np.asarray(mesh.vertices, np.float32) + shift), mesh.triangles,
                              {k: np.asarray(p, np.float32) + shift for k, p in mesh.edges.items()},
                              tuple(np.asarray(mesh.center, float) + shift), mesh.size, mesh.fine, mesh.face_ids)


def quick_mesh(env, spec, explode=0.0):
    """Uproszczony podgląd obudowy (bez Boolean): zewnętrzny prostopadłościan z krawędziami wnętrza; przy podziale wzdłuż
    osi - dwie części (pokrywa odsunięta o explode mm)."""
    lay = box_layout(env, spec)
    (ilo, ihi), (olo, ohi) = lay['inner'], lay['outer']
    top = spec.mode != 'open'
    inner = None if spec.mode == 'solid' else box_mesh(ilo, ihi, env, top=True, key0=100)
    if inner is not None:
        inner = kernel.DisplayMesh(inner.vertices, np.empty((0, 3), np.uint32), inner.edges, inner.center, inner.size)
    sp = split_of(spec)
    if sp['enabled'] and sp['mode'] in ('x', 'y', 'z'):
        i = 'xyz'.index(sp['mode'])
        s = split_position(env, spec, lay)
        if olo[i] < s < ohi[i]:
            bhi, llo = np.array(ohi, float), np.array(olo, float)
            bhi[i], llo[i] = s, s
            lid = box_mesh(llo, ohi, env, top=top or i != 2, key0=200)
            shift = np.asarray(env.axes, float)[i] * float(explode or 0.0)
            return merge_meshes([box_mesh(olo, bhi, env, top=True), moved_mesh(lid, shift), inner])
    return merge_meshes([box_mesh(olo, ohi, env, top=top), inner])


def side_handles(env, spec, lay):
    """Sześć strzałek na zewnętrznych ścianach obudowy (środek ściany, kierunek na zewnątrz): dict(side, start, dir)."""
    world = _world(env)
    ax = np.asarray(env.axes, float)
    olo, ohi = (np.asarray(p, float) for p in lay['outer'])
    mid = (olo + ohi) / 2
    out = []
    for side in SIDES:
        i, sign = AXIS_OF[side]
        p = mid.copy()
        p[i] = ohi[i] if sign > 0 else olo[i]
        out.append(dict(side=side, start=world(p), dir=ax[i] * sign))
    return out


def wall_slab(env, spec, lay, side):
    """Siatka ścianki obudowy po stronie side (od wnętrza do zewnątrz) - podświetlenie aktywnej ściany."""
    i, sign = AXIS_OF[side]
    (ilo, ihi), (olo, ohi) = (np.asarray(p, float) for p in lay['inner']), (np.asarray(p, float) for p in lay['outer'])
    lo, hi = olo.copy(), ohi.copy()
    if sign > 0:
        lo[i] = ihi[i] if spec.mode != 'solid' else ohi[i] - min(1.0, (ohi[i] - olo[i]) / 4)
        if hi[i] - lo[i] < 1e-3:
            lo[i] = hi[i] - .05
    else:
        hi[i] = ilo[i] if spec.mode != 'solid' else olo[i] + min(1.0, (ohi[i] - olo[i]) / 4)
        if hi[i] - lo[i] < 1e-3:
            hi[i] = lo[i] + .05
    return box_mesh(lo, hi, env)


def side_dimension_items(env, spec, lay, kind, prefix='encv'):
    """Wymiary przy strzałkach: odstęp (od elementów do wnętrza) albo grubość ścianki (od wnętrza do zewnątrz) w osi
    strzałki; kind='outer' - wymiary zewnętrzne X / Y / Z (wartości do wpisania)."""
    if kind == 'outer':
        return [dict(it, id=f'{prefix}:{it["label"]}') for it in outer_dimension_items(env, spec, prefix)]
    world = _world(env)
    half = np.asarray(env.size, float) / 2
    (ilo, ihi), (olo, ohi) = lay['inner'], lay['outer']
    c, w = clearance_of(spec), walls_of(spec)
    out = []
    for side in SIDES:
        i, sign = AXIS_OF[side]
        if kind == 'walls' and (spec.mode == 'solid' or (spec.mode == 'open' and side == 'z+')):
            continue
        a, b = np.zeros(3), np.zeros(3)
        if kind == 'clearance':
            a[i], b[i] = sign * half[i], (ihi[i] if sign > 0 else ilo[i])
            value = c[side]
        else:
            a[i], b[i] = (ihi[i], ohi[i]) if sign > 0 else (ilo[i], olo[i])
            value = w[WALL_OF[side]]
        out.append(dict(id=f'{prefix}:{side}', a=world(a), b=world(b), axis=None, value=float(value), sym=False, selected=False,
                        label=SIDE_LABELS[side] if kind == 'clearance' else SIDE_LABELS[WALL_OF[side]]))
    return out


# ---------------------------------------------------------------------------------------------- etap 4: podział obudowy
def split_of(spec):
    sp = dict(SPLIT_DEFAULTS)
    sp.update({k: v for k, v in (spec.split or {}).items()})
    return sp


def _outer_range(env, lay, n_world, origin):
    """Zakres obudowy wzdłuż normalnej (od punktu origin): min, max rzutów narożników zewnętrznych."""
    world = _world(env)
    (olo, ohi) = lay['outer']
    pts = [world([ohi[0] if k & 1 else olo[0], ohi[1] if k & 2 else olo[1], ohi[2] if k & 4 else olo[2]]) for k in range(8)]
    d = [float((p - origin) @ n_world) for p in pts]
    return min(d), max(d)


def split_base(env, spec, bodies=None):
    """Płaszczyzna odniesienia podziału (świat): punkt i normalna (pokrywa leży po stronie +normalnej)."""
    sp = split_of(spec)
    mode = sp['mode']
    ax = np.asarray(env.axes, float)
    if mode in ('x', 'y', 'z'):
        return np.asarray(env.center, float), ax['xyz'.index(mode)]
    if mode == 'plane':
        n = {'XY': (0, 0, 1.0), 'XZ': (0, 1.0, 0), 'YZ': (1.0, 0, 0)}.get(sp.get('plane'), (0, 0, 1.0))
        return np.zeros(3), np.asarray(n, float)
    if mode == 'face':
        face = sp.get('face') or {}
        owner = {b.id: b for b in (bodies or [])}.get(face.get('id'))
        if owner is None:
            raise kernel.CadError('Wskaż płaską ścianę elementu, według której obudowa ma być podzielona.')
        origin, _x, _y, z = face_frame(owner.shape, face['point'])
        return np.asarray(origin, float), np.asarray(z, float)
    raise kernel.CadError('Nieznany kierunek podziału.')


def split_plane(env, spec, lay, bodies=None):
    """Płaszczyzna podziału (świat): (punkt, normalna, (min, max) zakres obudowy wzdłuż normalnej od punktu odniesienia,
    położenie). Położenie: mm - od dolnej ściany obudowy (osie) albo od wskazanej płaszczyzny / ściany; % - część wymiaru
    obudowy w kierunku normalnej."""
    sp = split_of(spec)
    origin, n = split_base(env, spec, bodies)
    n = n / max(np.linalg.norm(n), 1e-12)
    lo, hi = _outer_range(env, lay, n, origin)
    pos = float(sp['position'])
    if not np.isfinite(pos):
        raise kernel.CadError('Położenie płaszczyzny podziału musi być liczbą.')
    if sp['unit'] == '%':
        d = lo + (hi - lo) * pos / 100.0
    elif sp['mode'] in ('x', 'y', 'z'):
        d = lo + pos
    else:
        d = pos
    if not (lo + 1e-3 < d < hi - 1e-3):
        raise kernel.CadError('Płaszczyzna podziału nie przecina obudowy - zmień położenie.')
    return origin + n * d, n, (lo, hi), d


def split_position(env, spec, lay):
    """Położenie płaszczyzny podziału wzdłuż osi przestrzeni (układ przestrzeni) - dla podziału wzdłuż X / Y / Z."""
    sp = split_of(spec)
    i = 'xyz'.index(sp['mode'])
    p, _n, _r, _d = split_plane(env, spec, lay)
    return float(np.asarray(env.axes, float)[i] @ (p - np.asarray(env.center, float)))


def _thick(spec):
    w = walls_of(spec)
    t_lo = np.array([w['x-'], w['y-'], w['bottom']])
    t_hi = np.array([w['x+'], w['y+'], 0.0 if spec.mode == 'open' else w['top']])
    return t_lo, t_hi


def split_check(env, spec, lay, bodies=None):
    """Walidacja parametrów podziału i połączenia (bez geometrii) - CadError z opisem. Zwraca płaszczyznę podziału."""
    sp = split_of(spec)
    if sp['mode'] not in SPLIT_MODES:
        raise kernel.CadError('Nieznany kierunek podziału.')
    if sp['joint'] not in JOINTS:
        raise kernel.CadError('Nieznany rodzaj połączenia.')
    plane = split_plane(env, spec, lay, bodies)
    if sp['joint'] == 'flat':
        return plane
    if spec.mode == 'solid':
        raise kernel.CadError('Pełna bryła nie ma ścianek - wybierz płaskie powierzchnie styku.')
    w, h, d, g = (float(sp[k]) for k in ('width', 'height', 'depth', 'gap'))
    if not all(np.isfinite(v) for v in (w, h, d, g)) or w <= 0 or h <= 0 or d <= 0 or g < 0:
        raise kernel.CadError('Szerokość, wysokość i głębokość połączenia muszą być większe od zera, a luz nie może być ujemny.')
    if d < h:
        raise kernel.CadError('Głębokość gniazda nie może być mniejsza od wysokości połączenia.')
    t_lo, t_hi = _thick(spec)
    ax = np.asarray(env.axes, float)
    n_l = ax @ plane[1]
    walls = [t for i in range(3) if abs(n_l[i]) < .999 for t in (t_lo[i], t_hi[i]) if not (i == 2 and spec.mode == 'open' and t == t_hi[2])]
    tmin = min(walls) if walls else 0.0
    need = w + (2 * g if sp['joint'] == 'tongue' else g)
    if need >= tmin - 1e-6:
        raise kernel.CadError(f'Połączenie (szerokość {w:g} + luz) nie mieści się w ściance {tmin:g} mm - zmniejsz szerokość lub luz.')
    (ilo, ihi) = lay['inner']
    world = _world(env)
    proj = [float((world([ihi[0] if k & 1 else ilo[0], ihi[1] if k & 2 else ilo[1], ihi[2] if k & 4 else ilo[2]]) - plane[0]) @ plane[1])
            for k in range(8)]
    if min(proj) > -d + 1e-6 or max(proj) < -1e-6:
        raise kernel.CadError(f'Płaszczyzna podziału musi przecinać ścianki boczne co najmniej {d:g} mm nad dnem wnętrza.')
    return plane


def _cq(shape):
    import cadquery as cq
    return cq.Shape.cast(shape) if not isinstance(shape, cq.Shape) else shape


def _boolean(kind, a, b, what):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    op = {'cut': BRepAlgoAPI_Cut, 'common': BRepAlgoAPI_Common, 'fuse': BRepAlgoAPI_Fuse}[kind](a, b)
    op.Build()
    if not op.IsDone():
        raise kernel.CadError(f'Operacja Boolean nie powiodła się ({what}).')
    return op.Shape()


def _solids(shape):
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    out = []
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        out.append(ex.Current())
        ex.Next()
    return out


def _volume(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return float(props.Mass()), np.array(props.CentreOfMass().Coord(), float)


def _single(shape, what):
    """Jedna poprawna bryła (fragmenty < 1e-6 mm³ po operacjach są pomijane)."""
    from OCP.BRepCheck import BRepCheck_Analyzer
    solids = [s for s in _solids(shape) if _volume(s)[0] > 1e-6]
    if len(solids) != 1:
        raise kernel.CadError(f'{what} nie jest jedną bryłą ({len(solids)} części) - zmień położenie podziału lub połączenie.')
    if not BRepCheck_Analyzer(solids[0]).IsValid():
        raise kernel.CadError(f'{what} ma niepoprawną geometrię (BRepCheck).')
    return solids[0]


def _unified(shape):
    """Scalenie współpłaszczyznowych ścian po operacjach Boolean (ShapeUpgrade_UnifySameDomain); przy kłopocie - bez zmian."""
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    try:
        unify = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
        unify.Build()
        return unify.Shape()
    except Exception:
        return shape


def local_enclosure(env, spec):
    """Obudowa w układzie przestrzeni (TopoDS) - przed przeniesieniem do świata."""
    lay = box_layout(env, spec)
    outer = _make_box(*lay['outer'])
    if spec.mode == 'solid':
        return outer, lay
    lo, hi = lay['inner']
    if spec.mode == 'open':
        hi = hi + np.array([0.0, 0.0, 1.0 + float(lay['outer_size'][2])])
    return _boolean('cut', outer, _make_box(lo, hi), 'wycięcie wnętrza'), lay


def _slab(p, n, low, high, size):
    """Warstwa między płaszczyznami p + n·low i p + n·high (duża w bok) - TopoDS w tym samym układzie co p, n."""
    n = n / np.linalg.norm(n)
    u = np.cross(n, (0, 0, 1.0) if abs(n[2]) < .9 else (1.0, 0, 0))
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    box = _cq(_make_box((-size, -size, low), (size, size, high)))
    return kernel.transformed(box, np.column_stack([u, v, n]), p).wrapped


def _ring(lay, a_lo, a_hi, b_lo, b_hi):
    """Pierścień wokół wnętrza: wnętrze powiększone o b minus wnętrze powiększone o a (wektory na stronę)."""
    ilo, ihi = (np.asarray(x, float) for x in lay['inner'])
    big = _make_box(ilo - b_lo, ihi + b_hi)
    if a_lo is None:
        return big
    return _boolean('cut', big, _make_box(ilo - a_lo, ihi + a_hi), 'pierścień połączenia')


def split_enclosure(env, spec, bodies=None, check_sources=True):
    """Podział obudowy na podstawę i pokrywę: BRepAlgoAPI_Splitter (płaszczyzna jako narzędzie), potem połączenie
    (zakładka wewnętrzna / zewnętrzna, pióro i wpust) operacjami Boolean: pokrywa dostaje występ, podstawa gniazdo
    powiększone o luz. Zwraca dict(base, lid, normal, joint) - bryły w świecie, każda sprawdzona BRepCheck_Analyzer.
    check_sources: występ połączenia nie może wchodzić w elementy wewnętrzne (CadError z nazwami)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.TopTools import TopTools_ListOfShape
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    sp = split_of(spec)
    E, lay = local_enclosure(env, spec)
    point, n_world, _rng, _d = split_check(env, spec, lay, bodies)
    c = np.asarray(env.center, float)
    ax = np.asarray(env.axes, float)
    p, n = ax @ (point - c), ax @ n_world
    size = 2.0 * float(np.linalg.norm(lay['outer_size'])) + 10.0
    face = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*map(float, p)), gp_Dir(*map(float, n))), -size, size, -size, size).Face()
    args, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(E)
    tools.Append(face)
    splitter = BRepAlgoAPI_Splitter()
    splitter.SetArguments(args)
    splitter.SetTools(tools)
    splitter.Build()
    if not splitter.IsDone():
        raise kernel.CadError('Podział obudowy płaszczyzną nie powiódł się (BRepAlgoAPI_Splitter).')
    base_parts, lid_parts = [], []
    for s in _solids(splitter.Shape()):
        vol, centre = _volume(s)
        if vol <= 1e-6:
            continue
        (lid_parts if float((centre - p) @ n) > 0 else base_parts).append(s)
    if not base_parts or not lid_parts:
        raise kernel.CadError('Płaszczyzna podziału nie dzieli obudowy na dwie części.')
    if len(base_parts) > 1 or len(lid_parts) > 1:
        raise kernel.CadError('Płaszczyzna dzieli obudowę na więcej niż dwie części - zmień położenie podziału.')
    base, lid = base_parts[0], lid_parts[0]
    lip = None
    joint = sp['joint'] if spec.mode != 'solid' else 'flat'
    if joint != 'flat':
        w, h, d, g = (float(sp[k]) for k in ('width', 'height', 'depth', 'gap'))
        t_lo, t_hi = _thick(spec)
        big = np.ones(3)
        if joint == 'lap_in':
            region = _ring(lay, np.zeros(3), np.zeros(3), np.full(3, w), np.full(3, w))
            seat = _ring(lay, None, None, np.full(3, w + g), np.full(3, w + g))
        elif joint == 'lap_out':
            region = _ring(lay, t_lo - w, t_hi - w, t_lo + big, t_hi + big)
            seat = _ring(lay, t_lo - w - g, t_hi - w - g, t_lo + big, t_hi + big)
        else:
            a_lo, a_hi = (t_lo - w) / 2, (t_hi - w) / 2
            region = _ring(lay, a_lo, a_hi, a_lo + w, a_hi + w)
            seat = _ring(lay, a_lo - g, a_hi - g, a_lo + w + g, a_hi + w + g)
        lip = _boolean('common', _boolean('common', region, _slab(p, n, -h, 0.0, size), 'występ połączenia'), E, 'występ w ściance')
        if _volume(lip)[0] <= 1e-6:
            raise kernel.CadError('Połączenie nie trafia w ścianki obudowy - zmień płaszczyznę podziału.')
        cut = _boolean('common', seat, _slab(p, n, -d, 1.0, size), 'gniazdo połączenia')
        base = _boolean('cut', base, cut, 'gniazdo w podstawie')
        lid = _boolean('fuse', lid, lip, 'występ pokrywy')
        base, lid = _unified(base), _unified(lid)
    base = _single(base, 'Podstawa')
    lid = _single(lid, 'Pokrywa')
    to_world = lambda s: kernel.transformed(_cq(s), ax.T, c)
    out = dict(base=check_solid(to_world(base).wrapped), lid=check_solid(to_world(lid).wrapped), normal=n_world, joint=joint)
    if check_sources and lip is not None and bodies is not None:
        hits = joint_collisions(to_world(lip), spec, bodies)
        if hits:
            raise kernel.CadError('Połączenie koliduje z elementami wewnętrznymi: ' + ', '.join(hits) + ' - zmień podział lub wymiary połączenia.')
    out['lip'] = None if lip is None else to_world(lip)
    return out


def joint_collisions(lip, spec, bodies):
    """Nazwy elementów źródłowych, w które wchodzi występ połączenia (część wspólna o objętości > 1e-4 mm³)."""
    by_id = {b.id: b for b in bodies}
    lip_box = lip.BoundingBox()
    hits = []
    for src in spec.sources:
        body = by_id.get(src.id)
        if body is None or body.kind != 'solid':
            continue
        bb = body.shape.BoundingBox()
        if (bb.xmax < lip_box.xmin or bb.xmin > lip_box.xmax or bb.ymax < lip_box.ymin or bb.ymin > lip_box.ymax
                or bb.zmax < lip_box.zmin or bb.zmin > lip_box.zmax):
            continue
        try:
            common = _boolean('common', lip.wrapped, body.shape.wrapped, 'kolizja')
        except kernel.CadError:
            hits.append(body.name)
            continue
        if _volume(common)[0] > 1e-4:
            hits.append(body.name)
    return hits
