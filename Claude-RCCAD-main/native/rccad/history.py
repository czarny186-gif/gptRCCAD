"""Historia parametryczna: przepisy operacji (JSON), ich ponowne wykonanie na zmienionym stanie i przeliczanie następnych kroków.
Czysta logika bez Qt: studio podaje stany (listy Body), a tu wyliczane są nowe stany po edycji któregoś kroku."""
from __future__ import annotations
import ast
import json
import re
import math
import operator
import uuid
from dataclasses import replace
import numpy as np
import cadquery as cq
from . import kernel
from . import sketchmeta as sm
from . import sheetmetal as shm
from . import sheetedit as she
from .document import Body

# klucz ikony kroku -> ikona paska narzędzi (icons.pixmap('t_' + nazwa)); wartości wspólne dla wszystkich kroków historii
ICONS = {'start': 'history', 'sketch': 'sketch', 'extrude': 'extrude', 'cut': 'cut', 'intersect': 'bool', 'bool': 'bool', 'mod': 'mod',
         'mirror': 'mirror', 'split': 'split', 'pattern': 'pattern', 'move': 'move', 'rotate': 'rotate', 'trash': 'trash', 'file': 'file', 'text': 'text', 'revolve': 'revolve', 'shell': 'shell', 'sweep': 'sweep', 'loft': 'loft', 'sheet': 'sheet', 'flange': 'flange', 'sheetbuild': 'flange', 'sheetmode':'unfold_sheet', 'unfold_sheet':'unfold_sheet', 'fold_sheet':'fold_sheet', 'sheet_sync':'sheet_sync', 'thread': 'thread',
         'ply': 'ply', 'ply_wall': 'ply_wall', 'ply_between': 'ply_between', 'ply_joints': 'ply_joints', 'ply_unfold': 'ply_unfold', 'ply_fold': 'ply_fold', 'tabwall': 'tabwall'}
# filtr paska historii: nazwa -> zbiór kluczy ikon (None = wszystko; 'stale' obsługiwane osobno)
FILTERS = {'Wszystkie kroki': None, 'Szkice i tekst': {'sketch', 'text'}, 'Operacje na bryłach': {'extrude', 'revolve', 'sweep', 'loft', 'cut', 'intersect', 'bool'},
           'Modyfikacje': {'mod', 'shell', 'split', 'mirror', 'pattern', 'move', 'rotate', 'trash'}, 'Import': {'file'}, 'Tylko błędy': 'stale'}


def passes_filter(info, name):
    """Czy krok pokazuje się przy danym filtrze paska historii."""
    allowed = FILTERS.get(name)
    if allowed is None:
        return True
    if allowed == 'stale':
        return bool(info.get('stale'))
    return info.get('icon') in allowed


# etykieta operacji uruchamianej przez run_operation -> klucz ikony
LABEL_ICONS = {'Tworzenie szkicu': 'sketch', 'Nożyczki': 'sketch', 'Zmiana wymiarów szkicu': 'sketch', 'Wyciągnięcie': 'extrude',
               'Wyciągnięcie (dodaj)': 'extrude', 'Obrót': 'revolve', 'Przeciągnięcie': 'sweep', 'Przeciągnięcie (dodaj)': 'sweep', 'Przeciągnięcie (wytnij)': 'cut', 'Przeciągnięcie (część wspólna)': 'intersect', 'Wyciągnięcie złożone': 'loft', 'Wyciągnięcie złożone (dodaj)': 'loft', 'Wyciągnięcie złożone (wytnij)': 'cut', 'Wyciągnięcie złożone (część wspólna)': 'intersect', 'Obrót (dodaj)': 'revolve', 'Obrót (wytnij)': 'cut', 'Obrót (część wspólna)': 'intersect', 'Wycięcie': 'cut', 'Część wspólna': 'intersect', 'Operacja na bryłach': 'bool',
               'Zaokrąglanie': 'mod', 'Skorupa': 'shell', 'Fazowanie': 'mod', 'Odbicie lustrzane': 'mirror', 'Przecięcie': 'split', 'Szyk': 'pattern', 'Przekształcenie': 'move', 'Dopasowanie': 'mate', 'Wyrównanie': 'align',
               'Wklejanie': 'file', 'Importowanie SVG': 'file', 'Importowanie modelu': 'file'}


def _num(value, unit=''):
    try:
        text = f'{float(value):.3f}'.rstrip('0').rstrip('.').replace('.', ',')
    except (TypeError, ValueError):
        return ''
    return text + unit


def step_label(info):
    """Opis kroku do paska historii: podstawowa nazwa i najważniejsze wartości z przepisu (liczone na bieżąco, więc po
    edycji kroku opis od razu pokazuje nowe wartości). Przykłady: „Kołnierz 20 mm, 90°”, „Przesunięcie X +15 mm”."""
    label = str(info.get('label', ''))
    op = info.get('op') if isinstance(info.get('op'), dict) else None
    if not op:
        return label
    kind = op.get('type')
    if kind == 'multi' and op.get('steps'):
        return f"{step_label(dict(info, op=op['steps'][0]))} ×{len(op['steps'])}"
    try:
        if kind == 'extrude' and isinstance(op.get('d1'), (int, float)):
            extra = {'symmetric': ' symetrycznie', 'two': f" + {_num(op.get('d2'), ' mm')}", 'ends': ' (oba końce)'}.get(op.get('dir'), '')
            return f"{label} {_num(op['d1'], ' mm')}{extra}"
        if kind == 'revolve' and isinstance(op.get('angle'), (int, float)):
            return f"{label} {_num(op['angle'], '°')}"
        if kind == 'shell' and isinstance(op.get('thickness'), (int, float)):
            return f"{label} {_num(op['thickness'], ' mm')}"
        if kind == 'mod' and isinstance(op.get('size'), (int, float)):
            return f"{label} {'R ' if op.get('kind') == 'fillet' else ''}{_num(op['size'], ' mm')}"
        if kind == 'sheet' and isinstance(op.get('t'), (int, float)):
            return f"{label} {_num(op['t'], ' mm')}"
        if kind == 'sheetbuild' and op.get('flanges') and label in ('Kołnierz', 'Zawinięcie'):
            last = op['flanges'][-1]
            if last.get('hem'):
                return f"Zawinięcie {_num(last['hem'].get('ret'), ' mm')}"
            return f"Kołnierz {_num(last.get('length'), ' mm')}, {_num(last.get('angle'), '°')}"
        if kind == 'transform' and isinstance(op.get('v'), list):
            parts = [f"{axis} {'+' if v > 0 else ''}{_num(v, ' mm' if op.get('mode') == 'move' else '°')}"
                     for axis, v in zip('XYZ', op['v']) if abs(float(v)) > 1e-9]
            return ('Przesunięcie ' if op.get('mode') == 'move' else 'Obrót ') + (', '.join(parts) or '0')
        if kind == 'split':
            how = {'plane': f"płaszczyzną {op.get('plane', '')}".rstrip(), 'face': 'równolegle do ściany', 'sketch': 'szkicem', 'body': 'bryłą'}.get(op.get('method'), '')
            off = op.get('offset')
            extra = f" {'+' if off > 0 else ''}{_num(off, ' mm')}" if isinstance(off, (int, float)) and abs(off) > 1e-9 and op.get('method') in ('plane', 'face') else ''
            return f"{label} {how}{extra}".strip()
        if kind == 'ply_panel' and isinstance(op.get('t'), (int, float)):
            return f"{label} {_num(op['t'], ' mm')}"
        if kind == 'ply_wall' and isinstance(op.get('h'), (int, float)):
            many = f" ×{len(op.get('edges') or [])}" if len(op.get('edges') or []) > 1 else ''
            return f"{label}{many} {_num(op['h'], ' mm')}"
        if kind == 'ply_between' and int(op.get('count', 1)) > 1:
            return f"{label} ×{int(op['count'])}"
        if kind == 'pattern' and isinstance(op.get('out'), list):
            return f"{label} ×{len(op['out']) + 1}"          # liczba elementów razem z oryginałem
    except Exception:
        return label
    return label


def plane_to_json(plane):
    return plane if isinstance(plane, str) else plane.to_dict()


def plane_from_json(value):
    return value if isinstance(value, str) else kernel.Frame.from_dict(value)


def plane_key(plane):
    return plane if isinstance(plane, str) else (plane.origin, plane.xdir, plane.normal)


def sketch_groups(bodies):
    """Widoczne szkice (bez konstrukcji i punktów) pogrupowane według rzeczywistej płaszczyzny: klucz -> (płaszczyzna, [bryły])."""
    groups = {}
    for b in bodies:
        if b.kind == 'sketch' and b.visible and not b.name.startswith(('Konstrukcja', 'Punkt')):
            plane = kernel.actual_frame(b.shape, b.plane)
            groups.setdefault(plane_key(plane), (plane, []))[1].append(b)
    return groups


def _unit(v):
    v = np.array(v, float)
    return v / np.linalg.norm(v)


def _edge_neighbours(shape):
    """Szybka mapa krawędź -> przylegające ściany (zamiast przeglądania wszystkich ścian dla każdej krawędzi)."""
    return kernel._edge_faces(shape)


def _adjacent_normals(shape, edge=None, vertex_point=None, neighbours=None):
    """Posortowane normalne ścian przylegających do krawędzi (lub wierzchołka): „podpis” elementu niezależny od rozmiaru bryły."""
    out = []
    if edge is not None and neighbours is not None:
        from OCP.TopoDS import TopoDS
        key = neighbours.FindIndex(edge.wrapped)
        faces = []
        for f in (neighbours.FindFromIndex(key) if key else []):
            face = cq.Face(TopoDS.Face_s(f))
            if not any(face.wrapped.IsSame(g.wrapped) for g in faces):
                faces.append(face)
        for face in faces:
            try:
                out.append([round(float(c), 3) for c in face.normalAt(edge.positionAt(.5)).toTuple()])
            except Exception:
                continue
        return sorted(out)
    for face in shape.Faces():
        try:
            if edge is not None:
                if not any(e.isSame(edge) for e in face.Edges()):
                    continue
                n = face.normalAt(edge.positionAt(.5)).toTuple()
            else:
                if not any(float(np.linalg.norm(np.array(v.toTuple()) - vertex_point)) < 1e-6 for v in face.Vertices()):
                    continue
                n = face.normalAt(cq.Vector(*[float(c) for c in vertex_point])).toTuple()
            out.append([round(float(c), 3) for c in n])
        except Exception:
            continue
    return sorted(out)


def _same_normals(a, b, tol=0.05):
    return len(a) == len(b) and all(float(np.linalg.norm(np.array(x) - np.array(y))) < tol for x, y in zip(sorted(a), sorted(b)))


def _scale(shape):
    box = kernel.bounds(shape)
    return max(box.xlen, box.ylen, box.zlen, 1e-6)


def _extent_along(shape, n):
    """(min, max) rzutu wierzchołków bryły na kierunek n."""
    values = [float(np.array(v.toTuple(), float) @ n) for v in shape.Vertices()]
    return (min(values), max(values)) if values else (0.0, 0.0)


def _extreme(shape, face, n):
    """'max' / 'min', gdy ściana leży na skraju bryły w kierunku normalnej (np. górna ściana), inaczej None."""
    if shape is None:
        return None
    lo, hi = _extent_along(shape, n)
    offset = float(np.array(face.Center().toTuple(), float) @ n)
    tol = 1e-6 * max(_scale(shape), 1.0)
    return 'max' if abs(offset - hi) < tol else 'min' if abs(offset - lo) < tol else None


def face_ref(face, normal, point, shape=None):
    c = np.array(face.Center().toTuple(), float)
    n = _unit(normal)
    ref = dict(normal=[float(x) for x in n], point=[float(x) for x in point], centroid=[float(x) for x in c], area=float(face.Area()))
    extreme = _extreme(shape, face, n)
    if extreme:
        ref['extreme'] = extreme      # ściana na skraju bryły (górna / dolna) zostaje na skraju po zmianie rozmiarów
    return ref


def match_face(shape, ref):
    """Płaska ściana bryły odpowiadająca zapisanej: najpierw ta, która nadal zawiera punkt; inaczej najlepiej pasująca
    (ta sama normalna, położenie płaszczyzny, środek i pole), więc krok przeżywa zmianę rozmiaru bryły."""
    n0 = _unit(ref['normal'])
    try:
        return kernel.face_at(shape, n0, ref['point'], curved=True)
    except kernel.CadError:
        pass
    c0, a0, scale = np.array(ref.get('centroid', ref['point']), float), float(ref.get('area', 0.0)), _scale(shape)
    lo, hi = _extent_along(shape, n0)
    want = ref.get('extreme')
    best = None
    for face in shape.Faces():
        if not kernel.is_planar_face(face):
            continue
        fn = np.array(face.normalAt().toTuple(), float)
        if float(fn @ n0) < .999:
            continue
        c = np.array(face.Center().toTuple(), float)
        d = c - c0
        off = abs(float(d @ n0))
        inplane = float(np.linalg.norm(d - float(d @ n0) * n0))
        area = float(face.Area())
        offset = float(c @ n0)
        at = 'max' if abs(offset - hi) < 1e-6 * max(scale, 1.0) else 'min' if abs(offset - lo) < 1e-6 * max(scale, 1.0) else None
        if want:
            # ściana była skrajna: skrajna ściana w tym samym kierunku wygrywa mimo zmiany położenia, nieskrajne dostają karę
            off = 0.0 if at == want else off + scale
        score = off + .25 * inplane + .5 * scale * abs(area - a0) / max(area, a0, 1e-9)
        if best is None or score < best[0]:
            best = (score, face, fn)
    if best is None or best[0] > 1.5 * scale:
        raise kernel.CadError('Ściana użyta w tym kroku już nie istnieje.')
    return best[1], best[2]


_NS = uuid.UUID('6f1c1a52-8b3e-4b77-9d6a-2c1f5e0a7b11')


def stable_id(seed, index):
    """Powtarzalny identyfikator (32 znaki hex) wynikający z ziarna kroku i numeru elementu - przeliczenie historii daje te same id."""
    return uuid.uuid5(_NS, f'{seed}:{index}').hex


def pad_ids(ids, count, seed):
    """Uzupełnia listę identyfikatorów wyników kroku do `count`: z ziarna, jeśli jest (powtarzalnie), inaczej losowo."""
    ids = list(ids)
    return ids + [stable_id(seed, i) if seed else uuid.uuid4().hex for i in range(len(ids), count)]


def new_text_group():
    """Znacznik grupy liter jednego napisu: 24 znaki hex, na pozycji 12 zawsze 'f' (zwykłe identyfikatory uuid4 mają tam '4')."""
    raw = uuid.uuid4().hex[:24]
    return raw[:12] + 'f' + raw[13:]


def text_ids(group, count):
    return [f'{group}{i:08x}' for i in range(count)]


def text_group_of(identifier):
    """Grupa napisu, do której należy szkic o danym identyfikatorze (albo None dla zwykłego szkicu)."""
    return identifier[:24] if isinstance(identifier, str) and len(identifier) == 32 and identifier[12] == 'f' else None


def _group_regions(plane, members, bodies=None):
    """Obszary szkiców w płaszczyźnie. Pojedynczy kształt (np. jeden okrąg) nie przechodzi przez General Fuse - wtedy obszarem jest ściana z jego konturu
    (tak samo jak przy wskazywaniu obszaru w oknie), inaczej przeliczenie historii gubiłoby takie kroki.
    bodies: gdy podane, obszary dzieli też obrys ścian brył leżących w tej płaszczyźnie (szkic wychodzący poza ścianę)."""
    try:
        faces = kernel.regions(plane, [e for b in members for e in b.shape.Edges()], [b.shape for b in members if b.shape.IsClosed()])
    except Exception:
        faces = []
    if not faces:
        for b in members:
            try:
                if b.shape.IsClosed():
                    faces.append(cq.Face.makeFromWires(b.shape))
            except Exception:
                continue
    if bodies is not None and faces:
        faces = split_on_solids(plane, faces, bodies)
    return faces


def split_on_solids(plane, faces, bodies):
    solids = [b.shape for b in bodies if b.kind == 'solid' and b.visible]
    try:
        return kernel.split_by_faces(faces, kernel.coplanar_faces(plane, solids))
    except Exception:
        return faces


def _inner_point(face):
    """Punkt leżący wewnątrz ściany (środek pierwszego trójkąta siatki) - środek ciężkości pierścienia leży poza nim."""
    vertices, triangles = face.tessellate(0.05, 0.2)
    if not triangles:
        return np.array(face.Center().toTuple(), float)
    t = triangles[0]
    return np.mean([np.array(vertices[i].toTuple(), float) for i in t], axis=0)


def material_faces(sketches):
    """Materiał zamkniętych szkiców (np. liter): kontury zagnieżdżone naprzemiennie dodają i odejmują obszar (litera - otwór + wyspa w otworze...),
    a kontury nakładające się bez zagnieżdżenia (częste w glifach, np. k, s, t) łączą się w jedną sumę - nic nie wypada z wyciągnięcia."""
    items = []
    for b in sketches:
        try:
            if b.shape.IsClosed():
                face = cq.Face.makeFromWires(b.shape)
                items.append((face, [np.array(v.toTuple(), float) for v in b.shape.Vertices()], float(face.Area())))
        except Exception:
            continue
    if not items:
        return []
    depth = []
    for i, (_, points, area) in enumerate(items):
        depth.append(sum(1 for j, (other, _, other_area) in enumerate(items)
                         if j != i and other_area > area and all(kernel.face_contains(other, p) for p in points)))
    material = None
    for level in sorted(set(depth)):
        faces = [items[i][0] for i in range(len(items)) if depth[i] == level]
        merged = faces[0] if len(faces) == 1 else faces[0].fuse(*faces[1:]).clean()
        if level % 2 == 0:
            material = merged if material is None else material.fuse(merged).clean()
        elif material is not None:
            material = material.cut(merged).clean()
    return list(material.Faces()) if material is not None else []


def material_regions(plane, members):
    """Obszary napisu będące materiałem liter (do wyciągania całego napisu)."""
    return material_faces(members)


def same_face(a, b):
    try:
        ca, cb = np.array(a.Center().toTuple(), float), np.array(b.Center().toTuple(), float)
        return abs(a.Area() - b.Area()) <= 1e-4 * max(a.Area(), 1e-9) and float(np.linalg.norm(ca - cb)) < 1e-3
    except Exception:
        return False


def coplanar_sketches(face, normal, bodies):
    """Widoczne, zamknięte szkice leżące w płaszczyźnie ściany i wewnątrz niej (np. okrąg lub napis narysowany na ścianie)."""
    n = _unit(normal)
    origin = np.array(face.Center().toTuple(), float)
    out = []
    for b in bodies:
        if b.kind != 'sketch' or not b.visible:
            continue
        try:
            if not b.shape.IsClosed():
                continue
            if any(abs(float((np.array(v.toTuple(), float) - origin) @ n)) > 1e-4 for v in b.shape.Vertices()):
                continue
            outline = cq.Face.makeFromWires(b.shape)
            if kernel.face_contains(face, _inner_point(outline)):
                out.append(b)
        except Exception:
            continue
    return out


def _frame_for(face, normal):
    n = _unit(normal)
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < .9 else np.array([0.0, 1.0, 0.0])
    xdir = _unit(np.cross(helper, n))
    return kernel.Frame(tuple(float(c) for c in face.Center().toTuple()), tuple(float(c) for c in xdir), tuple(float(c) for c in n))


def face_with_holes(face, normal, bodies):
    """Ściana bryły z otworami po zamkniętych szkicach narysowanych na niej (jak obszar wokół okręgu wewnątrz kwadratu):
    zwraca (lista obszarów ściany, szkice-otwory). Bez szkiców na ścianie wynikiem jest sama ściana."""
    sketches = coplanar_sketches(face, normal, bodies)
    if not sketches:
        return [face], []
    try:
        material = material_faces(sketches)
        if material:
            rest = face.cut(*material).clean() if len(material) > 1 else face.cut(material[0]).clean()
            kept = [f for f in rest.Faces() if f.Area() > 1e-6]
            if kept:
                return kept, sketches
    except Exception:
        pass
    return [face], []


def describe_profiles(profiles, bodies=(), merge=True):
    """Przepis na wybrane profile wyciągnięcia (src z Studio) -> lista słowników JSON. Obszar zapamiętuje też szkic-kotwicę
    i przesunięcie względem jego środka, więc podąża za szkicem po zmianie jego wymiarów."""
    out = []
    profiles = [p for p in profiles if not p.get('sibling')]      # pozostałe obszary tej samej ściany (wyspy): przepis odtwarza je razem z główną
    groups, boxes = None, {}           # liczone raz dla wszystkich profili (przy setkach otworów z szyku to sekundy)
    for src in profiles:
        if src['kind'] == 'sketch':
            out.append({'k': 'sketch', 'id': src['id']})
        elif src['kind'] == 'region':
            center = np.array(src['center'], float)
            spec = {'k': 'region', 'plane': plane_to_json(src['plane']), 'center': [float(c) for c in center], 'split': 1}
            if groups is None:
                groups = sketch_groups(bodies)
            group = groups.get(plane_key(src['plane']))
            best = None
            for b in (group[1] if group else []):
                if b.id not in boxes:
                    box = kernel.bounds(b.shape)
                    boxes[b.id] = (np.array((box.xmin, box.ymin, box.zmin)), np.array((box.xmax, box.ymax, box.zmax)))
                lo, hi = boxes[b.id]
                if np.all(center >= lo - 1e-6) and np.all(center <= hi + 1e-6):
                    size = float(np.prod(np.maximum(hi - lo, 1e-6)))
                    if best is None or size < best[0]:
                        best = (size, b.id, center - (lo + hi) / 2)
            if best is not None:
                spec['anchor'] = {'id': best[1], 'offset': [float(c) for c in best[2]]}
            out.append(spec)
        elif src['kind'] == 'cyl':      # ściana walcowa: oś, promień i punkt kliknięcia - odnajdywana po osi i promieniu
            info = src['cyl']
            out.append({'k': 'cyl', 'id': src['id'], 'origin': [float(c) for c in info['origin']], 'axis': [float(c) for c in info['axis']],
                        'radius': float(info['radius']), 'hit': [float(c) for c in src.get('hit', src['center'])], 'outward': int(info['outward'])})
        else:
            owner = next((b for b in bodies if b.id == src.get('id')), None)
            whole = src.get('whole') or src.get('face')
            ref = face_ref(whole, src['normal'], src.get('hit', src['center']), owner.shape if owner is not None else None) if whole is not None else dict(
                normal=[float(c) for c in src['normal']], point=[float(c) for c in src.get('hit', src['center'])])
            out.append(dict(ref, k='face', id=src['id'], **({'holes': True} if src.get('holes') else {})))
    return _merge_text_groups(out, profiles, bodies) if merge else out


def _merge_text_groups(out, profiles, bodies):
    """Gdy wybrano cały materiał napisu (obszary pokrywają go w całości), krok zapamiętuje „cały napis”: po zmianie treści obejmie też nowe litery."""
    picked = {}
    for n, spec in enumerate(out):
        group = text_group_of((spec.get('anchor') or {}).get('id')) if spec['k'] == 'region' else None
        if group:
            picked.setdefault((group, json.dumps(spec['plane'], sort_keys=True)), []).append(n)
    drop, extra = set(), []
    for (group, _), numbers in picked.items():
        spec = out[numbers[0]]
        try:
            plane = plane_from_json(spec['plane'])
            found = sketch_groups(bodies).get(plane_key(plane))
            members = [b for b in (found[1] if found else []) if text_group_of(b.id) == group]
            material = material_faces(members) if members else []
            total = sum(f.Area() for f in material)
            inside = [n for n in numbers if profiles[n].get('face') is not None
                      and any(kernel.face_contains(m, _inner_point(profiles[n]['face'])) for m in material)]
            covered = sum(profiles[n]['face'].Area() for n in inside)
            if material and covered >= 0.995 * total:
                drop |= set(inside)
                extra.append({'k': 'textgroup', 'group': group, 'plane': spec['plane']})
        except Exception:
            continue
    return [x for n, x in enumerate(out) if n not in drop] + extra


def match_cylinder(shape, spec):
    """Ściana walcowa bryły odpowiadająca zapisanej: ta sama oś (kierunek i położenie) i strona materiału; przy kilku -
    najbliższy promień, a potem najbliższa klikniętemu punktowi."""
    axis, origin = _unit(spec['axis']), np.array(spec['origin'], float)
    hit = np.array(spec['hit'], float)
    best = None
    for face in shape.Faces():
        if face.geomType() != 'CYLINDER':
            continue
        try:
            info = kernel.cylinder_info(face, shape)
        except Exception:
            continue
        if abs(abs(float(info['axis'] @ axis)) - 1) > 1e-6 or info['outward'] != int(spec.get('outward', info['outward'])):
            continue
        d = info['origin'] - origin
        if np.linalg.norm(d - float(d @ axis) * axis) > 1e-4 * max(1.0, _scale(shape)):
            continue
        score = (abs(info['radius'] - float(spec['radius'])), float(face.distance(cq.Vertex.makeVertex(*hit))))
        if best is None or score < best[0]:
            best = (score, face, info)
    if best is None:
        raise kernel.CadError('Ściana walcowa użyta w tym kroku już nie istnieje.')
    return best[1], best[2]


def resolve_profile(bodies, spec):
    """Odtwarza profil (wire, normal, plane, face) w podanym stanie albo rzuca CadError."""
    by_id = {b.id: b for b in bodies}
    if spec['k'] == 'cyl':
        body = by_id.get(spec['id'])
        if body is None or body.kind != 'solid':
            raise kernel.CadError('Bryła użyta w tym kroku już nie istnieje.')
        face, info = match_cylinder(body.shape, spec)
        normal = kernel.cylinder_normal(info, spec['hit'])
        return dict(wire=None, normal=tuple(float(c) for c in normal), plane=None, face=face, cyl=info)
    if spec['k'] == 'sketch':
        body = by_id.get(spec['id'])
        if body is None or body.kind != 'sketch':
            raise kernel.CadError('Szkic użyty w tym kroku już nie istnieje.')
        frame = kernel.frame_of(body.plane)
        normal = kernel.profile_normal(body.shape, frame.normal)
        tilted = abs(float(np.dot(normal, frame.normal))) < 1 - 1e-6
        return dict(wire=body.shape, normal=tuple(float(c) for c in normal), plane=None if tilted else body.plane, face=None)
    if spec['k'] == 'region':
        plane = plane_from_json(spec['plane'])
        group = sketch_groups(bodies).get(plane_key(plane))
        if group is None:
            raise kernel.CadError('Brak szkiców w płaszczyźnie tego kroku.')
        plane, members = group
        faces = _group_regions(plane, members, bodies if spec.get('split') else None)   # nowe kroki: obszar podzielony obrysem ściany
        if not faces:
            raise kernel.CadError('Szkic nie tworzy już zamkniętego obszaru.')
        center = np.array(spec['center'], float)
        anchor = spec.get('anchor')
        if anchor and anchor['id'] in by_id and by_id[anchor['id']].kind == 'sketch':      # obszar podąża za szkicem-kotwicą
            box = kernel.bounds(by_id[anchor['id']].shape)
            center = np.array((box.center.toTuple()), float) + np.array(anchor['offset'], float)
        inside = [f for f in faces if kernel.face_contains(f, center)]
        face = min(inside or faces, key=lambda f: float(np.linalg.norm(np.array(f.Center().toTuple()) - center)) if not inside else float(f.Area()))
        return dict(wire=face.outerWire(), normal=tuple(kernel.frame_of(plane).normal), plane=plane, face=face)
    body = by_id.get(spec['id'])
    if body is None or body.kind != 'solid':
        raise kernel.CadError('Bryła użyta w tym kroku już nie istnieje.')
    face, normal = match_face(body.shape, spec)
    if spec.get('holes'):      # szkice narysowane na ścianie (okrąg, napis...) tworzą w niej otwory, tak jak przy obszarach szkicu
        regions, sketches = face_with_holes(face, normal, bodies)
        if sketches:
            point = spec['point']
            sub = next((r for r in regions if kernel.face_contains(r, point)), None) or max(regions, key=lambda r: r.Area())
            return dict(wire=sub.outerWire(), normal=tuple(float(c) for c in normal), plane=None, face=sub, spent=[b.id for b in sketches])
    return dict(wire=face.outerWire(), normal=tuple(float(c) for c in normal), plane=None, face=face)


def resolve_profiles(bodies, spec):
    """Lista profili dla jednej pozycji przepisu (napis = wszystkie jego obszary, reszta = jeden profil)."""
    if spec['k'] == 'face' and spec.get('holes'):      # ściana z otworami po szkicach: cały jej materiał, także wyspy (wnętrza liter o, a, d, p...)
        body = next((b for b in bodies if b.id == spec['id']), None)
        if body is not None and body.kind == 'solid':
            face, normal = match_face(body.shape, spec)
            regions, sketches = face_with_holes(face, normal, bodies)
            if sketches:
                n = tuple(float(c) for c in normal)
                return [dict(wire=r.outerWire(), normal=n, plane=None, face=r, spent=[b.id for b in sketches]) for r in regions]
    if spec['k'] != 'textgroup':
        return [resolve_profile(bodies, spec)]
    plane = plane_from_json(spec['plane'])
    found = sketch_groups(bodies).get(plane_key(plane))
    members = [b for b in (found[1] if found else []) if text_group_of(b.id) == spec['group']]
    if not members:
        raise kernel.CadError('Napis użyty w tym kroku już nie istnieje.')
    faces = material_regions(found[0], members)
    if not faces:
        raise kernel.CadError('Napis nie tworzy już zamkniętych obszarów.')
    return [dict(wire=f.outerWire(), normal=tuple(kernel.frame_of(found[0]).normal), plane=found[0], face=f) for f in faces]


def make_tool(src, d1, d2, mode):
    if src.get('cyl') is not None:          # ściana walcowa: pierścień zmieniający promień (kierunek obustronny nie ma sensu)
        return kernel.cylinder_offset_tool(src['cyl'], d1)
    face, wire, normal, plane = src['face'], src['wire'], src['normal'], src['plane']
    if face is not None:
        return kernel.extrude_face(face, normal, d1, d2 if mode == 'two' else 0.0, mode == 'symmetric')
    if mode == 'two':
        return kernel.extrude_dir(wire, normal, d1, d2)
    if plane is not None:
        return kernel.extrude(wire, plane, d1, mode == 'symmetric')
    return kernel.extrude_dir(wire, normal, d1, 0.0, mode == 'symmetric')


def opposite_profile(bodies, src):
    """Wyciąganie „Na obu końcach”: przeciwległa płaska ściana tej samej bryły (np. spód sześcianu dla wskazanej góry).
    Szuka ściany o przeciwnej normalnej, w którą trafia prosta poprowadzona przez wnętrze profilu na wskroś bryły (najbliższa taka ściana),
    i zwraca (profil przesunięty na tę ścianę, normalna na zewnątrz przeciwległej ściany, znak: +1 gdy normalna profilu wychodzi z bryły)."""
    n = np.asarray(src['normal'], float)
    n = n / max(np.linalg.norm(n), 1e-12)
    face = src.get('face')
    if face is None:
        face = profile_face(src['wire'])
    if face is None:
        raise kernel.CadError('Profil musi być zamknięty.')
    p = _inner_point(face)
    solids = [b for b in bodies if b.kind == 'solid' and (src.get('kind') != 'face' or src.get('id') is None or b.id == src.get('id'))]
    eps = 1e-3
    best = None
    for out, sign in ((n, 1.0), (-n, -1.0)):         # szkic może mieć normalną skierowaną do wnętrza bryły
        for b in solids:
            try:
                if kernel.point_state(b.shape, p - out * eps) != 'in':
                    continue
            except Exception:
                continue
            for f in b.shape.Faces():
                try:
                    if not kernel.is_planar_face(f):
                        continue
                    fc = np.array(f.Center().toTuple(), float)
                    fn = np.array(f.normalAt(f.Center()).toTuple(), float)
                    if float(np.dot(fn, out)) > -1 + 1e-6:
                        continue
                    h = float(np.dot(p - fc, out))
                    if h <= 1e-4 or (best is not None and h >= best[0]):
                        continue
                    if not kernel.face_contains(f, p - out * h) or kernel.point_state(b.shape, p - out * (h / 2)) != 'in':
                        continue
                    best = (h, out, sign)
                except Exception:
                    continue
        if best is not None:
            break
    if best is None:
        raise kernel.CadError('Na obu końcach: nie znaleziono przeciwległej płaskiej ściany bryły dla wybranego profilu.')
    h, out, sign = best
    moved = face.translate(cq.Vector(*[float(c) for c in -out * h]))
    return moved, -out, sign


def opposite_tool(bodies, src, d1):
    """Narzędzie dla przeciwległej ściany: ta sama odległość, kierunek odbity (wyciągnięcie na zewnątrz albo wycięcie do środka)."""
    moved, normal, sign = opposite_profile(bodies, src)
    return kernel.extrude_face(moved, normal, float(d1) * sign)


def split_parts(bodies, only=None):
    """Bryła, która po wycięciu rozpadła się na części bez wspólnych styków, staje się osobnymi bryłami (największa zachowuje identyfikator,
    pozostałe dostają powtarzalne - przeliczenie historii daje te same obiekty). Dopiero Połącz skleja je z powrotem."""
    out = []
    for b in bodies:
        solids = b.shape.Solids() if (b.kind == 'solid' and (only is None or b.id in only)) else []
        if len(solids) < 2:
            out.append(b)
            continue
        for n, part in enumerate(sorted(solids, key=lambda s: -s.Volume())):
            out.append(b.changed(part) if n == 0 else Body(f'{b.name} — część {n + 1}', part, 'solid', b.plane, id=stable_id(f'{b.id}:part', n)).prepared())
    return out


def combine(existing, tools, op, spent=(), ids=(), name='Wyciągnięcie', skip=(), folder=''):
    """Nowe bryły albo operacja logiczna narzędzi z bryłami; użyte szkice wygasają.
    skip: bryły, których operacja nie zmienia (bryła wskazana tylko jako wysokość przy wyciąganiu do elementu, bryły ukryte na liście obiektów).
    folder: grupa na liście obiektów dla kilku nowych brył naraz (napis, szyk szkiców)."""
    skip = set(skip or ())
    fade = lambda bodies: [replace(b, visible=False) if b.id in spent else b for b in bodies]
    if op == 'new':
        ids2 = pad_ids(ids, len(tools), list(ids)[0] if ids else None)
        group = folder if len(tools) > 1 else ''
        return fade([*existing, *prepared_many(Body(name, t, id=ids2[i], folder=group) for i, t in enumerate(tools))])
    if op in ('cut', 'join') and len(tools) > 1:
        batched = _combine_batched(existing, tools, op, skip)
        if batched is not None:
            bodies, used, touched = batched
            if not used:
                raise kernel.CadError('Nie ma bryły, z którą można wykonać tę operację. Profil musi dotykać bryły lub ją przecinać.')
            return fade(split_parts(bodies, touched) if op != 'join' else bodies)
    bodies, used, touched = list(existing), False, set()
    for tool in tools:
        box = kernel.bounds(tool)
        for i, b in enumerate(bodies):
            if b.kind != 'solid' or b.id in skip:
                continue
            other = kernel.bounds(b.shape)
            if not _boxes_touch(box, other):
                continue
            try:
                bodies[i] = _boolean_changed(b, {'join': 'union', 'cut': 'subtract', 'intersect': 'intersect'}[op], [tool])
                used = True
                touched.add(b.id)
            except kernel.CadError:
                if op == 'cut' and _swallowed(b.shape, tool):
                    bodies[i] = None        # bryła leży w całości w wycinanym obszarze: wycięcie ją usuwa
                    used = True
                continue
        bodies = [b for b in bodies if b is not None]
    if not used:
        raise kernel.CadError('Nie ma bryły, z którą można wykonać tę operację. Profil musi dotykać bryły lub ją przecinać.')
    return fade(split_parts(bodies, touched) if op != 'join' else bodies)


def _remote_bodies(module, name, bodies, args, kwargs):
    """W procesie liczącym: funkcja (bryły, *args) -> lista brył. Bryły, których kształt się nie zmienił, wracają bez
    geometrii (tylko nazwa, widoczność, opis), więc przesyłane są wyłącznie nowe kształty z gotowymi siatkami."""
    import importlib
    function = getattr(importlib.import_module(module), name)
    result = function(list(bodies), *args, **kwargs)
    extra = None
    if isinstance(result, tuple):
        result, extra = result
    sources = {id(b.shape): b.id for b in bodies}
    packed = []
    for b in result:
        source = sources.get(id(b.shape))
        if source is not None:
            packed.append(('keep', source, dict(id=b.id, name=b.name, kind=b.kind, plane=b.plane, visible=b.visible, meta=b.meta, group=b.group, folder=b.folder, threads=b.threads)))
        else:
            packed.append(('body', b))
    return packed, extra


def offloaded(function, existing, *args, **kwargs):
    """function(bryły, *args) w procesie liczącym, gdy procesy są gotowe - okno w tym czasie działa normalnie (obracanie,
    oglądanie), bo liczenie nie trzyma blokady Pythona w procesie okna. Bez procesów - tutaj. Wynik jak function:
    lista brył albo (lista, dodatek)."""
    from . import workers
    existing = list(existing)
    if workers.ready():
        light = [replace(b, mesh=None) for b in existing]          # siatki nie są potrzebne do liczenia - nie przesyłamy ich
        try:
            packed, extra = workers.call_any(_remote_bodies, function.__module__, function.__name__, light, args, kwargs)
        except workers.Unavailable:
            packed = None
        if packed is not None:
            originals = {b.id: b for b in existing}
            out = []
            for item in packed:
                if item[0] == 'keep':
                    out.append(replace(originals[item[1]], **item[2]))
                else:
                    out.append(item[1])
            return (out, extra) if extra is not None else out
    return function(existing, *args, **kwargs)


def shape_job(module, name, args, solid=True):
    """W procesie liczącym: funkcja kernela zwracająca kształt + siatka do wyświetlania."""
    import importlib
    shape = getattr(importlib.import_module(module), name)(*args)
    return shape, kernel.display_mesh(shape, coarse=kernel.heavy(shape))


def offloaded_shape(function, *args):
    """(kształt, siatka albo None) - kształt z funkcji kernela liczony w procesie liczącym; bez procesów tutaj (siatka None)."""
    from . import workers
    if workers.ready():
        try:
            return workers.call_any(shape_job, function.__module__, function.__name__, args)
        except workers.Unavailable:
            pass
    return function(*args), None


def boolean_job(operation, base, tools, with_mesh):
    """W procesie liczącym: operacja logiczna i siatka wyniku. Zwraca (kształt, siatka albo None)."""
    shape = kernel.boolean(operation, base, tools)
    # duża bryła (np. płyta z setką otworów): zgrubna siatka od razu, dokładną dolicza w tle osobny proces
    return shape, (kernel.display_mesh(shape, coarse=kernel.heavy(shape)) if with_mesh else None)


def _boolean_changed(body, operation, tools):
    """Bryła po operacji logicznej. Przy gotowych procesach liczących operacja i siatka liczą się w procesie - wątek okna
    tylko czeka (bez blokady Pythona), więc okno się nie zacina nawet przy wycinaniu setek otworów naraz."""
    from . import workers
    if workers.ready():
        try:
            shape, mesh = workers.call_any(boolean_job, operation, body.shape, list(tools), not kernel.mesh_deferred())
            return body.changed(shape, mesh)
        except workers.Unavailable:
            pass
    return body.changed(kernel.boolean(operation, body.shape, list(tools)))


def prepared_many(bodies):
    """Siatki wielu nowych obiektów naraz (np. szyk, wyciągnięcie wielu profili): w procesach liczących równolegle,
    bez procesów - po kolei tutaj. W bloku deferred_mesh zostają bez siatek."""
    bodies = list(bodies)
    if kernel.mesh_deferred() or not bodies:
        return bodies
    from . import workers
    if len(bodies) >= 2 and workers.ready():
        out = []
        for b, (mesh, error) in zip(bodies, workers.mesh_many([(b.shape, b.kind == 'solid') for b in bodies])):
            if error is not None:
                raise kernel.CadError(error)
            out.append(replace(b, mesh=mesh))
        return out
    return [b.prepared() for b in bodies]


def _boxes_touch(box, other):
    return not (box.xmin > other.xmax + 1e-3 or box.xmax < other.xmin - 1e-3 or box.ymin > other.ymax + 1e-3 or
                box.ymax < other.ymin - 1e-3 or box.zmin > other.zmax + 1e-3 or box.zmax < other.zmin - 1e-3)


def _combine_batched(existing, tools, op, skip):
    """Wycięcie / połączenie wielu narzędzi naraz (np. 144 otwory z szyku): jedna operacja logiczna na bryłę ze wszystkimi
    narzędziami, które jej dotykają, i jedna nowa siatka - zamiast osobnej operacji i siatki po każdym otworze (czas rósł
    z kwadratem liczby otworów). Wynik taki sam jak po kolei. None, gdy coś się nie uda - wtedy liczy się po kolei."""
    try:
        boxes = [kernel.bounds(t) for t in tools]
        bodies, used, touched = list(existing), False, set()
        for i, b in enumerate(existing):
            if b.kind != 'solid' or b.id in skip:
                continue
            other = kernel.bounds(b.shape)
            mine = [n for n, box in enumerate(boxes) if _boxes_touch(box, other)]
            if op == 'join':        # połączenie powiększa bryłę: narzędzia dotykające dołączonej części też się łączą
                grown = True
                while grown:
                    grown = False
                    for n, box in enumerate(boxes):
                        if n not in mine and any(_boxes_touch(box, boxes[m]) for m in mine):
                            mine.append(n)
                            grown = True
            if not mine:
                continue
            chosen = [tools[n] for n in sorted(mine)]
            if op == 'cut' and any(_swallowed(b.shape, t) for t in chosen if _box_inside(other, kernel.bounds(t))):
                return None         # wycięcie usunęłoby całą bryłę - zachowanie jak po kolei
            bodies[i] = _boolean_changed(b, 'subtract' if op == 'cut' else 'union', chosen)
            used = True
            touched.add(b.id)
        return bodies, used, touched
    except Exception:
        return None


def _box_inside(inner, outer):
    return (inner.xmin >= outer.xmin - 1e-3 and inner.xmax <= outer.xmax + 1e-3 and inner.ymin >= outer.ymin - 1e-3 and
            inner.ymax <= outer.ymax + 1e-3 and inner.zmin >= outer.zmin - 1e-3 and inner.zmax <= outer.zmax + 1e-3)


def _swallowed(shape, tool):
    """Czy bryła mieści się w całości w narzędziu (wycięcie nie zostawia z niej nic)."""
    try:
        volume = float(shape.Volume())
        if volume <= 0:
            return False
        rest = shape.cut(tool)
        return float(rest.Volume()) <= max(1e-9, volume * 1e-7)
    except Exception:
        return False


def gap_pad(bodies, src):
    """Odstęp między płaszczyzną szkicu a skręconą (nie płaską) ścianą bryły pod nim; 0, gdy szkic leży na płaskiej ścianie albo w pustce."""
    plane = src.get('plane')
    if plane is None or src.get('wire') is None:
        return 0.0
    try:
        f = kernel.frame_of(plane)
        o, n = np.array(f.origin, float), np.array(f.normal, float)
        wire = src['wire']
        pts = [wire.positionAt(t) for t in np.linspace(0.0, 1.0, 13)] + [wire.Center()]
        pad = 0.0
        for body in bodies:
            if body.kind != 'solid':
                continue
            bb = body.shape.BoundingBox()
            limit = 0.1 * float(bb.DiagonalLength)
            faces = body.shape.Faces()
            for face in faces:       # szkic leży na płaskiej ścianie tej bryły: nic nie trzeba cofać
                if kernel.is_planar_face(face):
                    fn = np.array(face.normalAt().toTuple(), float)
                    if abs(float(fn @ n)) > 1 - 1e-6 and abs(float((np.array(face.Center().toTuple(), float) - o) @ n)) < 1e-4:
                        return 0.0
            near = [[float(face.distance(cq.Vertex.makeVertex(p.x, p.y, p.z))) for face in faces] for p in pts]      # odległość każdego punktu szkicu od każdej ściany
            centre = near[-1]
            nearest = min(range(len(faces)), key=lambda i: centre[i])
            if kernel.is_planar_face(faces[nearest]) or centre[nearest] > limit:
                continue
            pad = max(pad, max(min(row) for row in near))
        return pad + 1e-3 if pad > 1e-4 else 0.0
    except Exception:
        return 0.0


def run_extrude(bodies, recipe):
    """Ponownie wykonuje zapisane wyciągnięcie / wycięcie na podanym stanie."""
    mode = recipe.get('dir', 'one')
    sources = [src for spec in recipe['profiles'] for src in resolve_profiles(bodies, spec)]
    d1 = float(recipe['d1'])
    tools = []
    for src in sources:
        pad = gap_pad(bodies, src) if mode == 'one' else 0.0
        if pad > 0:      # szkic leży na płaszczyźnie przylegającej do skręconej ściany: narzędzie zaczyna się cofnięte, więc nie zostaje przerwa
            tools.append(make_tool(src, d1, -pad if d1 < 0 else pad, 'two'))
        else:
            tools.append(make_tool(src, d1, float(recipe.get('d2', 0)), mode))
    if mode == 'ends':        # na obu końcach: druga część na przeciwległej ścianie (liczona na stanie sprzed kroku)
        tools += [opposite_tool(bodies, src, d1) for src in sources]
    spent = set(recipe.get('spent', ()))
    for src in sources:
        spent |= set(src.get('spent', ()))
    groups = {spec['group'] for spec in recipe['profiles'] if spec['k'] == 'textgroup'}
    spent |= {b.id for b in bodies if text_group_of(b.id) in groups}      # wszystkie litery napisu (także nowe po zmianie treści)
    return combine(bodies, tools, recipe['mode'], spent, recipe.get('out', ()), skip=recipe.get('skip', ()), folder=recipe.get('folder', ''))


def profile_face(wire):
    try:
        return cq.Face.makeFromWires(wire)
    except Exception:
        return None


def profile_frame(src):
    """Układ współrzędnych profilu (początek, oś U, oś V, normalna). Szkic ma własną płaszczyznę; dla ściany bryły: początek = rzut początku
    układu na jej płaszczyznę, a osie U / V to rzuty osi X / Y świata (albo Z, gdy ściana leży prostopadle do nich)."""
    plane = src.get('plane')
    if plane is not None:
        f = kernel.frame_of(plane)
        return np.array(f.origin, float), np.array(f.xdir, float), np.array(f.ydir, float), np.array(f.normal, float)
    n = np.array(src['normal'], float)
    n /= np.linalg.norm(n)
    c = np.array(src['face'].Center().toTuple() if src.get('face') is not None else src['wire'].Center().toTuple(), float)
    origin = n * float(n @ c)
    axes = []
    for g in ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]):
        v = np.array(g) - n * float(np.array(g) @ n)
        if float(np.linalg.norm(v)) > 1e-6:
            axes.append(v / np.linalg.norm(v))
    u = axes[0]
    return origin, u, np.cross(n, u), n


def resolve_axis(spec, src):
    """Oś obrotu (punkt, kierunek) dla profilu: 'u' / 'v' = oś szkicu przez jego początek, 'line' = wskazana prosta (szkic lub krawędź)."""
    kind = spec['k']
    if kind == 'line':
        return np.array(spec['p'], float), np.array(spec['d'], float)
    origin, u, v, _ = profile_frame(src)
    return origin, (u if kind == 'u' else v)


def make_revolve(src, axis, angle):
    point, direction = resolve_axis(axis, src)
    face = src.get('face') or profile_face(src['wire'])
    if face is None:
        raise kernel.CadError('Profil obrotu musi być zamkniętym obszarem.')
    return kernel.revolve_face(face, point, direction, angle)


def run_revolve(bodies, recipe):
    """Ponownie wykonuje zapisany obrót profilu wokół osi."""
    sources = [src for spec in recipe['profiles'] for src in resolve_profiles(bodies, spec)]
    tools = [make_revolve(src, recipe['axis'], float(recipe.get('angle', 360))) for src in sources]
    spent = set(recipe.get('spent', ()))
    for src in sources:
        spent |= set(src.get('spent', ()))
    groups = {spec['group'] for spec in recipe['profiles'] if spec['k'] == 'textgroup'}
    spent |= {b.id for b in bodies if text_group_of(b.id) in groups}
    return combine(bodies, tools, recipe['mode'], spent, recipe.get('out', ()), 'Obrót', skip=recipe.get('skip', ()), folder=recipe.get('folder', ''))


def profile_outer(src):
    face = src.get('face') or profile_face(src['wire'])
    if face is None:
        raise kernel.CadError('Profil musi być zamkniętym obszarem.')
    return face


def resolve_path(bodies, spec):
    """Ścieżka przeciągnięcia: cały szkic (łamana, łuk) albo krawędź bryły odnaleziona po odwołaniu."""
    body = _body(bodies, spec['id'])
    if spec['k'] == 'sketch':
        return kernel.path_wire(body.shape)
    index = edge_indices(body.shape, [spec['ref']])[0]
    return kernel.path_wire(body.shape.Edges()[index])


def run_sweep(bodies, recipe):
    """Ponownie wykonuje przeciągnięcie profilu wzdłuż ścieżki."""
    sources = [src for spec in recipe['profiles'] for src in resolve_profiles(bodies, spec)]
    path = resolve_path(bodies, recipe['path'])
    tools = [kernel.sweep_face(profile_outer(src), path, bool(recipe.get('frenet'))) for src in sources]
    spent = set(recipe.get('spent', ()))
    for src in sources:
        spent |= set(src.get('spent', ()))
    return combine(bodies, tools, recipe['mode'], spent, recipe.get('out', ()), 'Przeciągnięcie', skip=recipe.get('skip', ()), folder=recipe.get('folder', ''))


def run_loft(bodies, recipe):
    """Ponownie wykonuje wyciągnięcie złożone przez zapisane profile (w zapisanej kolejności)."""
    wires = [profile_outer(resolve_profiles(bodies, spec)[0]).outerWire() for spec in recipe['profiles']]
    point = recipe.get('point')
    tool = kernel.loft_wires(wires, point['p'] if point else None, bool(recipe.get('ruled')))
    spent = set(recipe.get('spent', ()))
    return combine(bodies, [tool], recipe['mode'], spent, recipe.get('out', ()), 'Wyciągnięcie złożone', skip=recipe.get('skip', ()))


def _body(bodies, identifier):
    body = next((b for b in bodies if b.id == identifier), None)
    if body is None:
        raise kernel.CadError('Obiekt użyty w tym kroku już nie istnieje.')
    return body


def _replace(bodies, new):
    return [new if b.id == new.id else b for b in bodies]


def radial(center, pivot, axis, radius_now=None):
    """(odległość środka obiektu od osi, wersor promieniowy) - jak w panelu Szyk."""
    axis = np.array(axis, float)
    axis /= np.linalg.norm(axis)
    v = np.array(center, float) - np.array(pivot, float)
    r = v - float(v @ axis) * axis
    d = float(np.linalg.norm(r))
    if d > 1e-6:
        return d, r / d
    other = np.cross(axis, [0.0, 0.0, 1.0] if abs(axis[2]) < .9 else [1.0, 0.0, 0.0])
    return 0.0, other / np.linalg.norm(other)


def pattern_ops_for(body, recipe):
    """(kopie, przesunięcie oryginału albo None) dla zapisanych parametrów szyku i bieżącego położenia obiektu."""
    kind, p = recipe['kind'], recipe['params']
    if kind == 'circ':
        center = np.array(kernel.bounds(body.shape).center.toTuple(), float)
        d0, direction = radial(center, p['pivot'], p['axis'])
        offset = tuple(float(c) for c in direction * (float(p['radius']) - d0))
        ops = kernel.pattern_ops('circ', dict(p, offset=offset))
        return ops, (('t', offset) if max(abs(c) for c in offset) > 1e-9 else None)
    return kernel.pattern_ops(kind, p), None


def _moved_threads(threads, matrix):
    """Gwinty kosmetyczne kopii (szyk, lustro): przeniesione macierzą 4x4."""
    if not threads:
        return ()
    from . import threads as th
    return tuple(th.transformed(t, matrix) for t in threads)


def _mirror_matrix(normal, origin):
    n = _unit(normal)
    m = np.eye(4)
    m[:3, :3] = np.eye(3) - 2 * np.outer(n, n)
    m[:3, 3] = 2 * float(np.asarray(origin, float) @ n) * n
    return m


def run_pattern(bodies, recipe):
    body = _body(bodies, recipe['id'])
    ops, moved = pattern_ops_for(body, recipe)
    source = kernel.apply_op(body.shape, moved) if moved else body.shape
    copies = [kernel.apply_op(body.shape, op) for op in ops]
    if recipe.get('join') and body.kind == 'solid':
        merged = kernel.boolean('union', source, copies) if copies else source
        return _replace(bodies, body.changed(merged))
    out = pad_ids(recipe.get('out', ()), len(copies), (recipe.get('out') or [body.id])[0])
    group = (body.group or str(recipe['group'])) if recipe.get('group') else ''      # „jako jeden element”: oryginał i kopie w jednej grupie
    # osobne elementy: oryginał i kopie trafiają do wspólnej grupy (folderu) na liście obiektów
    folder = body.folder or ('' if group else (recipe.get('folder') or f'{body.name} — szyk'))
    made = prepared_many(Body(f'{body.name} — szyk {i + 1}', sh, body.kind, body.plane, id=out[i], group=group, folder=folder,
                              threads=_moved_threads(body.threads, kernel.op_matrix(ops[i])))
                         for i, sh in enumerate(copies))
    source_body = body.changed(source) if moved else body
    if group:
        source_body = replace(source_body, group=group)
    if folder != body.folder:
        source_body = replace(source_body, folder=folder)
    current = _replace(bodies, source_body) if (moved or group or folder != body.folder) else list(bodies)
    return [*current, *made]


def edge_refs(shape, indices):
    """Odwołania do krawędzi: środek, kierunek i normalne przylegających ścian (rozpoznanie niezależne od rozmiaru bryły)."""
    edges, out = shape.Edges(), []
    neighbours = _edge_neighbours(shape)
    for i in sorted(indices):
        e = edges[i]
        a, b = np.array(e.positionAt(0).toTuple(), float), np.array(e.positionAt(1).toTuple(), float)
        d = b - a
        out.append(dict(mid=[float(c) for c in e.positionAt(.5).toTuple()], dir=[float(c) for c in (d / max(np.linalg.norm(d), 1e-12))],
                        normals=_adjacent_normals(shape, edge=e, neighbours=neighbours)))
    return out


def edge_indices(shape, refs):
    """Krawędzie bryły odpowiadające zapisanym odwołaniom: ten sam kierunek i sąsiedztwo ścian, najbliższy środek."""
    scale = _scale(shape)
    tol = max(1e-3, 0.02 * scale)
    edges = shape.Edges()
    mids = np.array([e.positionAt(.5).toTuple() for e in edges], float)
    info = None
    out = []
    for ref in refs:
        if not isinstance(ref, dict):                       # stary format: sam środek
            d = np.linalg.norm(mids - np.array(ref, float), axis=1)
            i = int(np.argmin(d))
            if d[i] > tol:
                raise kernel.CadError('Krawędź użyta w tym kroku już nie istnieje.')
            out.append(i)
            continue
        if info is None:
            info = []
            neighbours = _edge_neighbours(shape)
            for e in edges:
                a, b = np.array(e.positionAt(0).toTuple(), float), np.array(e.positionAt(1).toTuple(), float)
                info.append((_unit(b - a) if np.linalg.norm(b - a) > 1e-12 else np.zeros(3), _adjacent_normals(shape, edge=e, neighbours=neighbours)))
        mid, direction = np.array(ref['mid'], float), np.array(ref['dir'], float)
        cands = [i for i, (d, n) in enumerate(info) if abs(float(d @ direction)) > .999 and _same_normals(n, ref['normals'])]
        if not cands:
            d = np.linalg.norm(mids - mid, axis=1)
            i = int(np.argmin(d))
            if d[i] > tol:
                raise kernel.CadError('Krawędź użyta w tym kroku już nie istnieje.')
            out.append(i)
            continue
        out.append(min(cands, key=lambda i: float(np.linalg.norm(mids[i] - mid))))
    return out


def vertex_refs(shape, points):
    return [dict(p=[float(c) for c in q], normals=_adjacent_normals(shape, vertex_point=np.array(q, float))) for q in points]


def vertex_points(shape, recipe):
    """Narożniki bryły odpowiadające zapisanym: ten sam układ przylegających ścian, najbliższy punkt."""
    refs = recipe.get('vrefs')
    if not refs:
        return [np.array(q, float) for q in recipe['verts']]
    pts = [np.array(v.toTuple(), float) for v in shape.Vertices()]
    tol = max(1e-3, 0.02 * _scale(shape))
    out = []
    for ref in refs:
        p0 = np.array(ref['p'], float)
        cands = [q for q in pts if _same_normals(_adjacent_normals(shape, vertex_point=q), ref['normals'])]
        pool = cands or [q for q in pts if float(np.linalg.norm(q - p0)) <= tol]
        if not pool:
            raise kernel.CadError('Narożnik użyty w tym kroku już nie istnieje.')
        out.append(min(pool, key=lambda q: float(np.linalg.norm(q - p0))))
    return out


def mod_many_job(shape, ids, points, size, kind):
    """Krawędzie, potem narożniki jednej bryły (narożniki odnajdywane po zaokrągleniu krawędzi)."""
    if ids:
        before = shape
        shape = kernel.blend(shape, set(ids), size, kind)
        if points:
            points = vertex_points(shape, dict(verts=[list(map(float, q)) for q in points], vrefs=vertex_refs(before, points)))
    if points:
        shape = kernel.blend_vertices(shape, [np.asarray(q, float) for q in points], size, kind)
    return shape


def mod_preview_many(jobs, size, kind, margin):
    """Podgląd kilku zaokrągleń / faz naraz (różne bryły, krawędzie i narożniki): siatka samych nowych powierzchni."""
    made = []
    for shape, ids, points in jobs:
        result = mod_many_job(shape, ids, points, size, kind)
        made += kernel.new_faces(shape, result) or []
    if not made:
        raise kernel.CadError('Ta wartość jest za duża dla wybranych elementów.')
    return kernel.display_mesh(kernel.compound(made), .3)


def run_mod(bodies, recipe):
    if recipe.get('items'):              # kilka brył albo krawędzie razem z narożnikami
        out = list(bodies)
        for item in recipe['items']:
            body = _body(out, item['id'])
            shape = body.shape
            if item.get('edges'):
                shape = kernel.blend(shape, set(edge_indices(shape, item['edges'])), float(recipe['size']), recipe['kind'])
            if item.get('verts'):
                shape = kernel.blend_vertices(shape, vertex_points(shape, item), float(recipe['size']), recipe['kind'])
            out = _replace(out, body.changed(shape))
        return out
    body = _body(bodies, recipe['id'])
    if recipe.get('verts'):
        shape = kernel.blend_vertices(body.shape, vertex_points(body.shape, recipe), float(recipe['size']), recipe['kind'])
    else:
        shape = kernel.blend(body.shape, set(edge_indices(body.shape, recipe['edges'])), float(recipe['size']), recipe['kind'])
    return _replace(bodies, body.changed(shape))


def outer_face_along(shape, normal):
    """Płaska ściana bryły zwrócona w kierunku normal, najdalej wysunięta w tę stronę (np. „górna” ściana) - do otwarcia
    tej samej ściany na kilku bryłach naraz. (ściana, normalna) albo None."""
    n = _unit(normal)
    best = None
    for f in shape.Faces():
        if f.geomType() != 'PLANE':
            continue
        fn = outward_normal(shape, f)
        if float(fn @ n) < 1 - 1e-4:
            continue
        level = float(np.array(f.Center().toTuple()) @ n)
        if best is None or level > best[0] + 1e-6 or (abs(level - best[0]) <= 1e-6 and f.Area() > best[1].Area()):
            best = (level, f, fn)
    return None if best is None else (best[1], best[2])


def run_shell(bodies, recipe):
    """Ponownie wykonuje skorupę: grubość, kierunek i otwarte ściany (odnajdywane na bryle po zmianie jej rozmiarów)."""
    body = _body(bodies, recipe['id'])
    faces = [match_face(body.shape, ref)[0] for ref in recipe.get('faces', ())]
    return _replace(bodies, body.changed(kernel.shell_solid(body.shape, faces, float(recipe['thickness']), bool(recipe.get('inward', True)))))


def run_transform(bodies, recipe):
    """Przesunięcie / obrót obiektu - albo całej grupy (ids, wspólny środek obrotu center)."""
    v = tuple(float(c) for c in recipe['v'])
    tr, rot = (v, (0, 0, 0)) if recipe['mode'] == 'move' else ((0, 0, 0), v)
    center = recipe.get('center')
    out = list(bodies)
    for identifier in recipe.get('ids') or [recipe['id']]:
        body = _body(out, identifier)
        shape = kernel.transform(body.shape, tr, rot, center)
        out = _replace(out, body.placed(shape, kernel.transform_matrix(body.shape, tr, rot, center)))
    return out


def outward_normal(shape, face, normal=None):
    """Normalna płaskiej ściany skierowana na zewnątrz bryły."""
    n = _unit(normal if normal is not None else face.normalAt(face.Center()).toTuple())
    c = np.array(face.Center().toTuple(), float)
    eps = 1e-3 * max(1.0, _scale(shape))
    try:
        if kernel.point_state(shape, c + n * eps) == 'in' and kernel.point_state(shape, c - n * eps) != 'in':
            n = -n
    except Exception:
        pass
    return n


def _rotation_between(a, b):
    """Macierz obrotu 3x3 przeprowadzająca wektor jednostkowy a na b (najkrótszy obrót; dla przeciwnych - 180° wokół prostopadłej)."""
    a, b = _unit(a), _unit(b)
    c = float(np.clip(a @ b, -1.0, 1.0))
    if c > 1 - 1e-12:
        return np.eye(3)
    if c < -1 + 1e-12:
        helper = np.array([1.0, 0, 0]) if abs(a[0]) < .9 else np.array([0, 1.0, 0])
        axis = _unit(np.cross(a, helper))
        return 2 * np.outer(axis, axis) - np.eye(3)
    v = np.cross(a, b)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1 / (1 + c))


def _axis_rotation(axis, degrees):
    """Macierz obrotu o kąt (stopnie) wokół osi przechodzącej przez początek układu (wzór Rodriguesa)."""
    k = _unit(axis)
    a = np.radians(float(degrees))
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * (K @ K)


def placement(mode, face, normal, target, tnormal, spin=0.0):
    """Macierz 3x4 przekształcenia przesuwanej bryły.
    mate (Dopasowanie): ściana obraca się tak, by patrzeć wprost na ścianę docelową (normalne przeciwne), a jej środek trafia
    w środek ściany docelowej - bryły stykają się tymi ścianami. align (Wyrównanie): bez obrotu, przesunięcie wzdłuż normalnej
    ściany wzorcowej, aż obie ściany leżą na tej samej wysokości (w jednej płaszczyźnie)."""
    ca, cb = (np.array(f.Center().toTuple(), float) for f in (face, target))
    na, nb = _unit(normal), _unit(tnormal)
    if mode == 'align':
        R, t = np.eye(3), float((cb - ca) @ nb) * nb
    elif mode == 'mate':
        # spin: dodatkowy obrót (np. co 45°) wokół normalnej ściany docelowej przez jej środek - ściany dalej przylegają
        R = _axis_rotation(nb, spin) @ _rotation_between(na, -nb)
        t = cb - R @ ca
    else:
        raise kernel.CadError('Nieznany rodzaj dopasowania.')
    return np.hstack([R, t.reshape(3, 1)])


def apply_placement(shape, matrix):
    """Sztywne przekształcenie bryły (obrót + przesunięcie) macierzą 3x4; obrót ortonormalizowany przed użyciem."""
    from OCP.gp import gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    M = np.asarray(matrix, float)
    u, _, vt = np.linalg.svd(M[:, :3])
    R = u @ vt
    if np.linalg.det(R) < 0:
        raise kernel.CadError('Nieprawidłowe przekształcenie bryły.')
    trsf = gp_Trsf()
    trsf.SetValues(*[float(R[i, j]) if j < 3 else float(M[i, 3]) for i in range(3) for j in range(4)])
    moved = cq.Shape.cast(BRepBuilderAPI_Transform(shape.wrapped, trsf, True).Shape())
    return kernel.valid(moved, bool(shape.Solids()))


def run_mate(bodies, recipe):
    """Dopasowanie / Wyrównanie: przesuwana bryła ustawiana względem ściany innej bryły (ściany odszukiwane na nowo, więc krok
    przeżywa zmianę wcześniejszych kroków)."""
    body, target = _body(bodies, recipe['id']), _body(bodies, recipe['target'])
    if body.id == target.id:
        raise kernel.CadError('Wybierz ściany dwóch różnych brył.')
    face, _ = match_face(body.shape, recipe['face'])
    tface, _ = match_face(target.shape, recipe['tface'])
    matrix = placement(recipe['mode'], face, outward_normal(body.shape, face), tface, outward_normal(target.shape, tface),
                       float(recipe.get('spin', 0.0)))
    return _replace(bodies, body.placed(apply_placement(body.shape, matrix), matrix))


def run_mirror(bodies, recipe):
    body = _body(bodies, recipe['id'])
    shape = kernel.mirror_plane(body.shape, recipe['normal'], recipe['origin'])
    if recipe.get('join') and body.kind == 'solid':
        return _replace(bodies, body.changed(kernel.boolean('union', body.shape, [shape])))
    mirrored = Body(body.name + ' — odbicie', shape, body.kind, body.plane, id=recipe.get('out') or uuid.uuid4().hex,
                    threads=_moved_threads(body.threads, _mirror_matrix(recipe['normal'], recipe['origin']))).prepared()
    if recipe.get('keep'):
        return [*bodies, mirrored]
    return [mirrored if b.id == body.id else b for b in bodies]


def split_shapes(bodies, recipe):
    """Części bryły po przecięciu: [(kształt, strona)] wg metody z kroku."""
    body = _body(bodies, recipe['id'])
    method = recipe['method']
    if method in ('plane', 'face'):
        n = np.array(recipe['normal'], float)
        n = n / np.linalg.norm(n)
        origin = np.array(recipe['origin'], float) + n * float(recipe.get('offset', 0.0))
        return kernel.split_plane(body.shape, n, origin)
    if method == 'sketch':
        tool = _body(bodies, recipe['tool'])
        members = [b.shape for b in bodies if tool.group and b.group == tool.group and b.kind == 'sketch' and b.visible] or [tool.shape]
        try:
            normal = np.asarray(kernel.frame_of(tool.plane).normal, float)   # płaszczyzna szkicu - także dla pojedynczej linii
        except Exception:
            normal = None
        return kernel.split_sketch(body.shape, members[0] if len(members) == 1 else kernel.compound(members), normal)
    if method == 'body':
        return kernel.split_body(body.shape, _body(bodies, recipe['tool']).shape)
    raise kernel.CadError('Nieznana metoda przecięcia.')


def run_split(bodies, recipe):
    """Przetnij bryłę: części stają się osobnymi bryłami (największa zachowuje identyfikator). keep: 'both' albo strona 1 / 2.
    Użyty szkic wygasa; bryła-narzędzie zostaje."""
    body = _body(bodies, recipe['id'])
    keep = recipe.get('keep', 'both')
    parts = [s for s, side in split_shapes(bodies, recipe) if keep == 'both' or side == int(keep)]
    if not parts:
        raise kernel.CadError('Po tej stronie cięcia nie ma żadnej części bryły.')
    parts.sort(key=lambda s: -s.Volume())
    seed = recipe.get('out') or body.id
    new = [body.changed(part) if n == 0 else Body(f'{body.name} — część {n + 1}', part, 'solid', body.plane, id=stable_id(f'{seed}:split', n)).prepared()
           for n, part in enumerate(parts)]
    out = []
    for b in bodies:
        if b.id == body.id:
            out.extend(new)
        elif recipe['method'] == 'sketch' and (b.id == recipe.get('tool') or (b.group and b.group == _body(bodies, recipe['tool']).group)):
            out.append(replace(b, visible=False))
        else:
            out.append(b)
    return out


def run_bool(bodies, recipe):
    base = _body(bodies, recipe['base'])
    tools = [_body(bodies, i) for i in recipe['tools']]
    result = base.changed(kernel.boolean(recipe['op'], base.shape, [t.shape for t in tools]))
    if recipe['op'] == 'subtract' and any(t.threads for t in tools):
        from . import threads as th        # wycięcie bryłą z gwintem: w otworze zostaje gwint wewnętrzny
        made = th.cut_threads(base.shape, [g for t in tools for g in t.threads])
        if made:
            result = replace(result, threads=(*result.threads, *made))
    gone = set(recipe['tools'])
    out = [result if b.id == base.id else b for b in bodies if recipe.get('keep') or b.id not in gone]
    return split_parts(out, {base.id}) if recipe['op'] != 'union' else out


def run_sheet(bodies, recipe):
    """Konwersja na blachę: sprawdza, że wskazana ściana jest prostokątem na prostopadłościanie (sam krok nie zmienia bryły)."""
    body = _body(bodies, recipe['id'])
    face = match_face(body.shape, recipe['face'])[0]
    info=shm.sheet_of_face(body.shape, face)
    nominal=dict(base=recipe.get('base',info['base']),t=recipe.get('t',info['t']),flanges=[],rules=recipe.get('rules') or {})
    return _replace(bodies,replace(body,meta={'sheet':she.state(nominal)}))


def run_flange(bodies, recipe):
    """Kołnierz na krawędzi blachy. Grubość i normalna blachy zapisane w kroku (z konwersji)."""
    body = _body(bodies, recipe['id'])
    index = edge_indices(body.shape, recipe['edges'])[0]
    edge = body.shape.Edges()[index]
    shape = shm.add_flange(body.shape, edge, recipe['sheet'], float(recipe['radius']), float(recipe['angle']), float(recipe['length']),
                           float(recipe.get('gap', 0.0)), recipe.get('relief', 'none'), float(recipe.get('relief_size', 0.0)))
    return _replace(bodies, body.changed(shape))


def sheet_job(kind, shape, source, args, with_mesh):
    """Operacja na blasze (budowa z kołnierzami / rozłożenie / zgięcie) - w procesie liczącym przypisanym do tej blachy
    (pamięta jej wcześniejsze cięcia i rozwinięcia) albo tutaj. Zwraca (kształt, stan blachy, siatka albo None)."""
    if kind == 'build':
        shape, metadata = she.rebuild(shape, source, args) if source else (shm.build_sheet(args), she.state(args))
    else:
        flat, sync = args
        shape, metadata = she.switch(shape, source, flat, sync)
    mesh = kernel.display_mesh(shape) if with_mesh else None
    return shape, metadata, mesh


def sheet_warm(recipe):
    """W procesie blachy: rozwinięcie przygotowane zawczasu (Rozłóż / Zegnij potem prawie natychmiast)."""
    return she.warm(recipe)


def _sheet_result(bodies, body, kind, source, args):
    """Wynik operacji na blasze: w procesie liczącym tej blachy (okno się nie zacina - czeka bez blokady Pythona),
    a bez procesów - jak dotąd w tym wątku."""
    from . import workers
    with_mesh = not kernel.mesh_deferred()
    place = 'sheet'
    if kind == 'mode':
        # rozłożenie / zgięcie: proces rozwinięć, jeśli zdążył już przygotować rozwinięcie tej blachy; inaczej proces budowy
        # tej blachy (ma ją gotową w pamięci, więc liczy tylko rozwinięcie)
        try:
            if workers.prepared(('layout', she._layout_key(source.get('recipe') or {}))):
                place = 'layout'
        except Exception:
            pass
    if kind == 'build' and workers.ready():
        # budowa blachy: kierowana stąd, ale ciężkie części liczą procesy - cięcia narożników kołnierzy jednego poziomu
        # równolegle (każdy kołnierz w swoim procesie, który pamięta jego cięcia), łączenie części i siatka też w procesach;
        # tutaj zostaje tylko lekkie planowanie, więc okno się nie zacina
        shape, metadata, _ = sheet_job(kind, body.shape, source, args, False)
        mesh = None
        if with_mesh:
            try:
                mesh, error = workers.call_any(workers._mesh_job, shape, .12, True, False)
                if error:
                    raise kernel.CadError(error)
            except workers.Unavailable:
                mesh = None
        out = replace(body, shape=shape, mesh=mesh, meta={'sheet': metadata}) if mesh is not None or not with_mesh else replace(body.changed(shape), meta={'sheet': metadata})
        return _replace(bodies, out)
    try:
        shape, metadata, mesh = workers.call_affine((place, body.id), sheet_job, kind, body.shape, source, args, with_mesh)
        out = replace(body, shape=shape, mesh=mesh, meta={'sheet': metadata})
    except workers.Unavailable:
        shape, metadata, _ = sheet_job(kind, body.shape, source, args, False)
        out = replace(body.changed(shape), meta={'sheet': metadata})
    return _replace(bodies, out)


def run_sheetbuild(bodies, recipe):
    """Blacha od podstaw: płyta bazowa i lista kołnierzy zapisane w kroku (geometria liczy się z nich, nie z poprzedniego stanu)."""
    body = _body(bodies, recipe['id'])
    return _sheet_result(bodies, body, 'build', (body.meta or {}).get('sheet'), recipe)


def run_sheetmode(bodies,recipe):
    body=_body(bodies,recipe['id'])
    source=(body.meta or {}).get('sheet') or recipe['state']
    out=_sheet_result(bodies, body, 'mode', source, (recipe['flat'], recipe.get('sync', False)))
    if recipe.get('sync'):
        return out
    return sheet_tabs_switch(out, body, _body(out, body.id), bool(recipe['flat']))


def sheet_tab_walls(bodies, sheet_id):
    """Ścianki na noski blachy (także ścianki na ściankach) - najpierw te bliżej blachy."""
    children = {}
    for b in bodies:
        tab = ((b.meta or {}).get('ply') or {}).get('tab')
        if tab and tab.get('sheet'):
            children.setdefault(tab['sheet'], []).append(b)
    out, queue = [], [sheet_id]
    while queue:
        for c in children.get(queue.pop(0), ()):
            if c not in out:
                out.append(c)
                queue.append(c.id)
    return out


def _sheet_frame(sheet):
    from . import plywood as pw
    base = (((sheet.meta or {}).get('sheet') or {}).get('recipe') or {}).get('base')
    return pw.frame_matrix(base['o'], base['x'], base['y'], base['z']) if base else np.eye(4)


def _np44(matrix):
    return np.array([[matrix[r, c] for c in range(4)] for r in range(4)], float)


def sheet_tab_matrices(bodies, before, after, flat):
    """Przekształcenia ścianek na noski przy rozkładaniu (flat=True) / składaniu blachy: {id: macierz 4x4}.
    Rozkładanie: ścianka kładzie się płasko obok płyty, na której stoi (obrót na zawiasie), i jedzie razem z tą płytą
    do rozwinięcia (ta sama macierz co płyta blachy). Składanie: zapamiętane położenie, z przesunięciem blachy."""
    from . import plywood as pw
    walls = sheet_tab_walls(bodies, before.id)
    if not walls:
        return {}
    out = {}
    if flat:
        state = (before.meta or {}).get('sheet') or {}
        if state.get('flat'):
            return {}
        model = she.layout(state['recipe'])
        t = float(state['recipe']['t'])
        folded = {b.id: b.shape for b in walls}
        for w in walls:
            if w.meta['ply'].get('tab', {}).get('unfold'):
                continue
            parent = w.meta['ply']['tab']['sheet']
            wt = float(w.meta['ply'].get('t') or t)
            if parent == before.id:
                panel = min(model.panels, key=lambda p: p.folded.distance(w.shape))
                place = _np44(panel.flat_frame) @ np.linalg.inv(_np44(panel.folded_frame))
                out[w.id] = place @ pw.hinge_matrix(w.shape, panel.folded, wt)
            elif parent in out and parent in folded:
                out[w.id] = out[parent] @ pw.hinge_matrix(w.shape, folded[parent], wt)
        return out
    for w in walls:
        info = w.meta['ply'].get('tab', {}).get('unfold')
        if not info:
            continue
        ref = pw._mat(info.get('ref'))
        sheet_move = _sheet_frame(after) @ np.linalg.inv(ref)
        out[w.id] = sheet_move @ pw._mat(info['M']) @ np.linalg.inv(pw._mat(info.get('acc')))
    return out


def sheet_tabs_switch(bodies, before, after, flat):
    """Blacha rozłożona / zgięta: jej ścianki na noski rozkładają się / składają razem z nią (tylko przesunięcie płyt,
    siatki przekształcane)."""
    from . import plywood as pw
    moves = sheet_tab_matrices(bodies, before, after, flat)
    if not moves:
        return bodies
    ref = pw._lst(_sheet_frame(after))
    result = []
    for b in bodies:
        m = moves.get(b.id)
        if m is None:
            result.append(b)
            continue
        ply = dict(b.meta['ply'])
        tab = dict(ply['tab'])
        if flat:
            tab['unfold'] = dict(M=pw._lst(np.linalg.inv(m)), acc=pw._lst(np.eye(4)), ref=ref)
        else:
            tab.pop('unfold', None)
        ply['tab'] = tab
        shape = pw.apply_matrix(b.shape, m)
        result.append(replace(b, shape=shape, mesh=kernel.mesh_moved(b.mesh, m) if b.mesh is not None else _deferred_or_mesh(shape),
                              meta=dict(b.meta, ply=ply)))
    return result


def run_text(bodies, recipe):
    """Dodaje szkic z tekstem (litery i ich otwory jako osobne druty) w zapisanej płaszczyźnie."""
    plane = plane_from_json(recipe['plane'])
    q = recipe['params']
    shapes = kernel.text_shape(plane, q['text'], *q['anchor'], size=q['size'], font=q['font'], bold=q['bold'], italic=q['italic'], angle=q['angle'])
    ids = list(recipe.get('out', ()))
    group = text_group_of(ids[0]) if ids else None
    if group:      # identyfikatory liter wynikają z grupy napisu, więc po zmianie treści kolejne kroki nadal je znajdują
        ids = text_ids(group, len(shapes))
    else:
        ids = pad_ids(ids, len(shapes), ids[0] if ids else None)
    folder = text_folder(q['text'])        # napis od razu jako grupa na liście obiektów
    return [*bodies, *[Body(recipe['name'], sh, 'sketch', plane, id=ids[i], folder=folder).prepared() for i, sh in enumerate(shapes)]]


def text_folder(text):
    text = ' '.join(str(text).split())
    return f'Tekst „{text[:28]}{"…" if len(text) > 28 else ""}”'


def run_delete(bodies, recipe):
    gone = set(recipe['ids'])
    return [b for b in bodies if b.id not in gone]


def run_rename(bodies, recipe):
    body = _body(bodies, recipe['id'])
    return _replace(bodies, replace(body, name=recipe['name']))


def run_thread(bodies, recipe):
    """Gwinty na walcach brył (jeden albo kilka naraz - items): opcjonalnie otwór / wałek na właściwą średnicę;
    gwint kosmetyczny (opis przy bryle) albo od razu prawdziwe zwoje (real)."""
    from . import threads as th
    out = list(bodies)
    for item in recipe.get('items') or [recipe]:
        body = _body(out, item['id'])
        c = item['cylinder']
        info = th.find_cylinder(body.shape, c['origin'], c['axis'], c['radius'])
        if info is None:
            raise kernel.CadError('Nie znaleziono otworu / wałka pod gwint.')
        info['internal'] = bool(c.get('internal', info['internal']))
        spec = item['spec']
        _, d, pitch = th.size(spec['standard'], spec['size'])
        shape = body.shape
        want = th.bore(spec['standard'], d, pitch, info['internal'])
        if item.get('adjust') and abs(want - 2 * info['radius']) > 1e-3:
            shape = th.set_diameter(shape, info, want)
        thread = th.make_thread(info, spec['standard'], spec['size'], spec.get('hand', 'right'), spec['start'], spec['end'])
        if recipe.get('real'):
            out = _replace(out, body.changed(th.real_shape(shape, [thread])))       # od razu prawdziwe zwoje
        else:
            new = body.changed(shape) if shape is not body.shape else body
            out = _replace(out, replace(new, threads=(*body.threads, thread)))
    return out


def run_thread_real(bodies, recipe):
    """Gwint kosmetyczny zamieniony na prawdziwe zwoje (ten sam rozmiar, zakres i kierunek)."""
    from . import threads as th
    body = _body(bodies, recipe['id'])
    index = th.thread_index(body.threads, recipe['thread'])
    if index is None:
        raise kernel.CadError('Ta bryła nie ma już tego gwintu.')
    thread = body.threads[index]
    shape = th.real_shape(body.shape, [thread])
    rest = tuple(t for k, t in enumerate(body.threads) if k != index)
    return _replace(bodies, replace(body.changed(shape), threads=rest))


# ---------- sklejka: płyty, ścianki, półki, połączenia ----------
def _next_names(bodies, base, count):
    """Kolejne wolne nazwy „Płyta 1”, „Płyta 2”…"""
    used = {b.name for b in bodies}
    out, k = [], 1
    while len(out) < count:
        name = f'{base} {k}'
        if name not in used:
            out.append(name)
        k += 1
    return out


def _ply_bodies(bodies, shapes, base, recipe, folder=''):
    from . import plywood as pw
    ids = pad_ids(recipe.get('out', ()), len(shapes), (recipe.get('out') or [None])[0])
    names = _next_names(bodies, base, len(shapes))
    meta = pw.ply_meta(recipe['t'], recipe.get('method', 'cnc'))
    return prepared_many(Body(names[i], shp, id=ids[i], meta=meta, folder=folder) for i, shp in enumerate(shapes))


def run_ply_panel(bodies, recipe):
    """Płyty ze szkiców / ścian: profil wyciągnięty na grubość sklejki (d - grubość ze znakiem strony)."""
    sources = [src for spec in recipe['profiles'] for src in resolve_profiles(bodies, spec)]
    if not sources:
        raise kernel.CadError('Brak profilu płyty.')
    shapes = [make_tool(src, float(recipe['d']), 0.0, 'one') for src in sources]
    spent = set(recipe.get('spent', ()))
    for src in sources:
        spent |= set(src.get('spent', ()))
    fade = [replace(b, visible=False) if b.id in spent else b for b in bodies]
    return [*fade, *_ply_bodies(bodies, shapes, 'Płyta', recipe)]


def _ply_trim(shape, others):
    """Nowa płyta bez części nachodzących na inne płyty - tylko się z nimi styka (połączenia dodaje osobny krok)."""
    for other in others:
        bb, ob = shape.BoundingBox(), other.BoundingBox()
        if bb.xmax < ob.xmin or ob.xmax < bb.xmin or bb.ymax < ob.ymin or ob.ymax < bb.ymin or bb.zmax < ob.zmin or ob.zmax < bb.zmin:
            continue
        try:
            if shape.intersect(other).Volume() > 1e-6:
                shape = kernel.boolean('subtract', shape, [other])
        except kernel.CadError:
            pass
    if shape.Solids():
        shape = max(shape.Solids(), key=lambda x: x.Volume())
    return kernel.valid(shape)


def _ply_others(bodies, skip=()):
    from . import plywood as pw
    return [b.shape for b in bodies if b.kind == 'solid' and b.visible and b.id not in skip and pw.is_panel(b)]


def _nominal_edge(sheet, edge):
    """Krawędź płyty bazowej blachy w pełnej długości (z zapisu blachy): gniazda wycięte wcześniej przy narożniku
    (noski sąsiedniej ścianki) nie skracają nowej ścianki. Inne krawędzie (kołnierz, ścianka) - bez zmian.
    Zwraca (krawędź, płyta albo None)."""
    state = ((sheet.meta or {}).get('sheet') or {}).get('recipe')
    if not state or edge.geomType() != 'LINE':
        return edge, None
    try:
        base = shm.base_solid(state['base'])
    except Exception:
        return edge, None
    a, b = np.array(edge.startPoint().toTuple(), float), np.array(edge.endPoint().toTuple(), float)
    d = _unit(b - a)
    for e in base.Edges():
        if e.geomType() != 'LINE':
            continue
        p, q = np.array(e.startPoint().toTuple(), float), np.array(e.endPoint().toTuple(), float)
        u = _unit(q - p)
        if abs(abs(float(u @ d)) - 1) > 1e-6:
            continue
        off = (a - p) - u * float((a - p) @ u)
        if np.linalg.norm(off) > 1e-4:
            continue
        lo, hi = sorted((0.0, float((q - p) @ u)))
        s0, s1 = sorted((float((a - p) @ u), float((b - p) @ u)))
        if not (s0 >= lo - 1e-4 and s1 <= hi + 1e-4):
            continue
        # przedłużenie tylko przez puste gniazdo (noski sąsiedniej ścianki): gdy za końcem jest materiał (gięcie
        # sąsiedniego kołnierza), koniec zostaje - inaczej gniazda trafiłyby w łuk gięcia
        from . import plywood as pw
        t = float(state['t'])
        try:
            plate, n = pw.edge_plate(sheet.shape, edge, t)
        except kernel.CadError:
            return edge, None
        inward = np.cross(n, u)
        if float((np.array(plate.Center().toTuple(), float) - a) @ inward) < 0:
            inward = -inward                     # w głąb płyty (próbka nie może leżeć na ścianie czołowej)
        reach = 1.5 * t + .5
        ends = []
        for s_end, sign, limit in ((s0, -1.0, lo), (s1, 1.0, hi)):
            point = p + u * s_end
            probe = point + u * sign * .05 - n * (t / 2) + inward * min(.2, t / 4)
            void = kernel.point_state(sheet.shape, tuple(probe)) == 'out'
            ends.append(max(limit, s_end - reach) if sign < 0 and void else min(limit, s_end + reach) if sign > 0 and void else s_end)
        if ends[1] - ends[0] <= s1 - s0 + 1e-9:
            return edge, base
        return cq.Edge.makeLine(cq.Vector(*(p + u * ends[0])), cq.Vector(*(p + u * ends[1]))), base
    return edge, None


def run_sheet_tabwall(bodies, recipe):
    """Kołnierz na noski (Blacha): płaska ścianka zamiast gięcia na krawędzi blachy (albo innej takiej ścianki), połączona
    noskami z płytą, z której wychodzi, i z sąsiednimi ściankami na noski. Blacha dostaje gniazda / noski jak przy
    zwykłym cięciu (zmiana kształtu blachy), ścianka jest osobną płytą (do cięcia jak płyty ze Sklejki)."""
    from . import plywood as pw
    sheet = _body(bodies, recipe['id'])
    index = edge_indices(sheet.shape, recipe['edges'])[0]
    edge = sheet.shape.Edges()[index]
    t = float(recipe['t'])
    try:
        flat_region, _n = pw.edge_plate(sheet.shape, edge, t)      # płaska część płyty: tylko tu wolno ciąć gniazda
    except kernel.CadError:
        flat_region = None
    edge, plate = _nominal_edge(sheet, edge)
    wall, plate, _up = pw.tab_wall(sheet.shape, edge, t, float(recipe['length']), recipe.get('measure', 'outer'), bool(recipe.get('flip')), plate)
    neighbours = [b for b in bodies if b.kind == 'solid' and b.visible and b.id != sheet.id and pw.is_panel(b) and pw._boxes_near(wall, b.shape)]
    wall = _ply_trim(wall, [sheet.shape, *[b.shape for b in neighbours]])
    wid = (recipe.get('out') or [uuid.uuid4().hex])[0] if isinstance(recipe.get('out'), list) else (recipe.get('out') or uuid.uuid4().hex)
    wp = dict(id=wid, shape=wall, **pw.panel_info(wall, t))
    platep = dict(id=sheet.id, shape=plate, **pw.panel_info(plate, t))
    contacts = [c for c in pw.find_contacts([wp, platep])[0]]
    if not contacts:
        raise kernel.CadError('Ścianka nie styka się z płytą blachy - sprawdź krawędź i stronę.')
    near = [dict(id=b.id, shape=b.shape, **pw.panel_info(b.shape, (b.meta or {}).get('ply', {}).get('t'))) for b in neighbours]
    for c in pw.find_contacts([wp, *near])[0]:
        if wid in (c['a'], c['b']):
            contacts.append(c)
    meth = 'laser'
    for c in contacts:
        c['joint'] = pw.joint_for(meth, c['kind'])
    shapes = {wid: (wall, wp['n']), sheet.id: (sheet.shape, platep['n'])}
    for p in near:
        shapes[p['id']] = (p['shape'], p['n'])
    failures = []
    out = pw.apply_joints(shapes, contacts, dict(method=meth, width=float(recipe.get('width') or 0), fit=float(recipe.get('fit', 0.0))),
                          failures=failures)
    failed = {k for k, _ in failures}
    main = f'{wid}:{sheet.id}' if any(c['a'] == wid and c['b'] == sheet.id for c in contacts) else f'{sheet.id}:{wid}'
    if main in failed:
        raise kernel.CadError('Nie udało się połączyć ścianki z blachą noskami: ' + next(m for k, m in failures if k == main))
    partners = {wid: set()}
    for c in contacts:
        key = c.get('key', f"{c['a']}:{c['b']}")
        if key in failed:
            continue
        other = c['b'] if c['a'] == wid else c['a']
        partners[wid].add(other)
        partners.setdefault(other, set()).add(wid)
    if sheet.id in out and flat_region is not None and (sheet.meta or {}).get('sheet'):
        # gniazda (z luzem) tylko w płaskiej części blachy - nie w łuku gięcia sąsiedniego kołnierza
        try:
            removed = kernel.boolean('subtract', sheet.shape, [out[sheet.id]]) if sheet.shape.Volume() > out[sheet.id].Volume() - 1e-9 else None
        except kernel.CadError:
            removed = None
        try:
            added = kernel.boolean('subtract', out[sheet.id], [sheet.shape])
        except kernel.CadError:
            added = None
        new_shape = sheet.shape
        if removed is not None and removed.Solids():
            cut = pw._common(removed, flat_region)
            if cut is not None:
                new_shape = kernel.boolean('subtract', new_shape, [cut])
        if added is not None and added.Solids() and added.Volume() > 1e-6:
            new_shape = kernel.boolean('union', new_shape, [added])
        out[sheet.id] = new_shape
    # blacha i jej ścianki na noski - jedna grupa (jeden element: zaznaczanie, przesuwanie, biblioteka)
    root = sheet
    seen = set()
    while ((root.meta or {}).get('ply') or {}).get('tab') and root.id not in seen:
        seen.add(root.id)
        parent = next((b for b in bodies if b.id == root.meta['ply']['tab'].get('sheet')), None)
        if parent is None:
            break
        root = parent
    group = root.group or sheet.group or recipe.get('group') or ('t' + sheet.id)[:32]
    members = {root.id, sheet.id, *(b.id for b in sheet_tab_walls(bodies, root.id))}
    result = []
    for b in bodies:
        if b.id in members and b.group != group:
            b = replace(b, group=group)
        if b.id in out and b.id != wid:
            changed = b.changed(out[b.id])
            if pw.is_panel(changed) and b.id in partners:
                ply = dict(changed.meta['ply'], joined=sorted(set(changed.meta['ply'].get('joined', ())) | partners[b.id]))
                changed = replace(changed, meta=dict(changed.meta, ply=ply))
            result.append(changed)
        else:
            result.append(b)
    meta = pw.ply_meta(t, meth)
    meta['ply']['joined'] = sorted(partners[wid])
    meta['ply']['tab'] = dict(sheet=sheet.id, length=float(recipe['length']), measure=recipe.get('measure', 'outer'))
    name = _next_names(bodies, 'Ścianka blachy', 1)[0]
    new = Body(name, out.get(wid, wall), id=wid, meta=meta, folder=sheet.folder, group=group).prepared()
    return [*result, new]


def _wall_params(recipe):
    return dict(t=float(recipe['t']), h=float(recipe['h']), side=recipe.get('side', 'on'), flip=bool(recipe.get('flip')))


def ply_neighbour_walls(bodies, base, indices, recipe):
    """Ścianki tej samej podstawy (jeszcze bez połączeń, z tymi samymi ustawieniami) stykające się narożnikiem z nowymi
    krawędziami: przeliczane razem z nowymi, żeby ścianki dodawane po jednej schodziły się tak samo jak dodane naraz.
    Zwraca {indeks krawędzi: id ścianki}."""
    from . import plywood as pw
    params = _wall_params(recipe)
    edges = base.shape.Edges()
    ends = []
    for i in indices:
        e = edges[i]
        ends += [np.array(e.startPoint().toTuple(), float), np.array(e.endPoint().toTuple(), float)]
    out = {}
    for b in bodies:
        ply = (b.meta or {}).get('ply') or {}
        info = ply.get('wall')
        if b.kind != 'solid' or not info or info.get('base') != base.id or ply.get('joined') or ply.get('fold'):
            continue
        if any(abs(float(info.get(k, 0)) - float(params[k])) > 1e-9 for k in ('t', 'h')) or info.get('side') != params['side'] \
                or bool(info.get('flip')) != params['flip']:
            continue
        try:
            j = edge_indices(base.shape, [info['edge']])[0]
        except Exception:
            continue
        if j in indices:
            continue
        e = edges[j]
        pts = (np.array(e.startPoint().toTuple(), float), np.array(e.endPoint().toTuple(), float))
        if any(np.linalg.norm(p - q) < 1e-5 for p in pts for q in ends):
            out[j] = b.id
    return out


def ply_walls(bodies, base, indices, recipe, neighbours=None):
    """Ścianki na krawędziach płyty-podstawy. Najdłuższe krawędzie najpierw: w narożnikach prostych dłuższe ścianki biegną
    przez całą długość, krótsze mieszczą się między nimi; w narożnikach pod innym kątem ścianki schodzą się na skos.
    Kolejne ścianki i inne płyty nie nachodzą na siebie. neighbours ({indeks: id}) - istniejące ścianki przeliczane
    razem z nowymi; zwraca wtedy (nowe ścianki, {id: nowy kształt sąsiada})."""
    from . import plywood as pw
    edges = base.shape.Edges()
    base_t = (base.meta or {}).get('ply', {}).get('t') if base.meta else None
    redo = dict(neighbours or {})
    others = _ply_others(bodies, {base.id, *recipe.get('ignore', ()), *redo.values()})     # płyty ukryte na liście obiektów - pomijane
    every = [*indices, *redo]
    order = sorted(every, key=lambda i: -edges[i].Length())
    made = pw.edge_walls(base.shape, [edges[i] for i in order], float(recipe['t']), float(recipe['h']), recipe.get('side', 'on'),
                         bool(recipe.get('flip')), base_t)
    shapes = {i: wall for i, (wall, _) in zip(order, made)}
    done = []
    result = {}
    for i in order:
        result[i] = _ply_trim(shapes[i], [*others, *done])
        done.append(result[i])
    walls = [result[i] for i in sorted(indices, key=lambda i: -edges[i].Length())]
    if neighbours is None:
        return walls
    return walls, {bid: result[i] for i, bid in redo.items()}


def ply_folder(bodies, base):
    """Grupa pudełka na liście obiektów: grupa podstawy albo nowa „Pudełko N”."""
    if base.folder:
        return base.folder
    used = {b.folder for b in bodies if b.folder}
    k = 1
    while f'Pudełko {k}' in used:
        k += 1
    return f'Pudełko {k}'


def run_ply_wall(bodies, recipe):
    """Ścianki; podstawa i ścianki trafiają do jednej grupy (całe pudełko razem na liście obiektów). Ścianki pamiętają
    krawędź podstawy, z której powstały - kolejne ścianki dodane obok przeliczają ich narożniki (jak przy dodaniu naraz)."""
    base = _body(bodies, recipe['base'])
    indices = edge_indices(base.shape, recipe['edges'])
    neighbours = ply_neighbour_walls(bodies, base, indices, recipe)
    walls, redone = ply_walls(bodies, base, indices, recipe, neighbours)
    folder = recipe.get('folder') or ply_folder(bodies, base)
    kept = [replace(b, folder=folder) if b.id == base.id else (b.changed(redone[b.id]) if b.id in redone else b) for b in bodies]
    order = sorted(indices, key=lambda i: -base.shape.Edges()[i].Length())
    made = _ply_bodies(bodies, walls, 'Ścianka', recipe, folder)
    info = _wall_params(recipe)
    tagged = []
    for body, i in zip(made, order):
        ply = dict(body.meta['ply'], wall=dict(info, base=base.id, edge=edge_refs(base.shape, [i])[0]))
        tagged.append(replace(body, meta=dict(body.meta, ply=ply)))
    return [*kept, *tagged]


def ply_between_shapes(bodies, recipe):
    from . import plywood as pw
    a, b = _body(bodies, recipe['a']['id']), _body(bodies, recipe['b']['id'])
    fa, na = match_face(a.shape, recipe['a'])
    fb, _ = match_face(b.shape, recipe['b'])
    pa = np.array(fa.Center().toTuple(), float)
    pb = np.array(fb.Center().toTuple(), float)
    return pw.between_panels(fa, pa, na, fb, pb, float(recipe['t']), recipe.get('pos'), int(recipe.get('count', 1)), bool(recipe.get('turn')))


def ply_between_fit(bodies, shapes, recipe):
    """Nowe półki / przegrody wpasowane między istniejące płyty: przechodzące na wylot przez prostopadłą płytę dostają
    z nią nacięcia krzyżowe, a z pozostałymi tylko się stykają (przycięte). Płyty ukryte na liście obiektów (recipe['ignore'])
    są dla nowych płyt niewidoczne - nowe dodają się tak, jakby ich nie było.
    Zwraca (kształty nowych płyt, {id: zmieniona istniejąca płyta}, {id: id płyt połączonych krzyżowo})."""
    from . import plywood as pw
    ignore = set(recipe.get('ignore', ()))
    panels = [b for b in bodies if b.kind == 'solid' and b.visible and pw.is_panel(b) and b.id not in ignore]
    current = {b.id: b.shape for b in panels}
    joined = {}
    out = []
    for k, shp in enumerate(shapes):
        others = [(b.id, current[b.id], b.meta['ply'].get('t')) for b in panels]
        shp, changed, crossed = pw.cross_new(shp, float(recipe['t']), others, recipe.get('method', 'cnc'), recipe.get('fit'),
                                              recipe.get('tool'), recipe.get('corner', 'dog'))
        current.update(changed)
        joined[k] = crossed
        rest = [current[b.id] for b in panels if b.id not in crossed]
        before = shp.Volume()
        shp = _ply_trim(shp, rest)
        if shp.Volume() < .2 * before:
            raise kernel.CadError('W tym miejscu jest już płyta - nowa by się w niej zmieściła.')
        out.append(shp)
    changed = {pid: shape for pid, shape in current.items() if shape is not next(b.shape for b in panels if b.id == pid)}
    return out, changed, joined


def run_ply_between(bodies, recipe):
    shapes, _ = ply_between_shapes(bodies, recipe)
    shapes, changed, joined = ply_between_fit(bodies, shapes, recipe)
    a, b = _body(bodies, recipe['a']['id']), _body(bodies, recipe['b']['id'])
    folder = a.folder or b.folder                     # półka w grupie szafki / pudełka
    made = _ply_bodies(bodies, shapes, 'Półka' if not recipe.get('turn') else 'Przegroda', recipe, folder)
    partners = {}
    for k, crossed in joined.items():
        for oid in crossed:
            partners.setdefault(oid, set()).add(made[k].id)
            partners.setdefault(made[k].id, set()).add(oid)
    out = []
    for body in [*bodies, *made]:
        if body.id in changed:
            body = body.changed(changed[body.id])
        if body.id in partners:
            ply = dict(body.meta['ply'])
            ply['joined'] = sorted(set(ply.get('joined', ())) | partners[body.id])
            body = replace(body, meta={**(body.meta or {}), 'ply': ply})
        out.append(body)
    return out


def ply_contacts(bodies, recipe):
    """Styki płyt z kroku połączeń z wybranym połączeniem (zapisane dla pary albo domyślne dla metody)."""
    from . import plywood as pw
    ids = set(recipe['ids'])
    panels = pw.panels_of([b for b in bodies if b.id in ids])
    contacts, skipped = pw.find_contacts(panels)
    chosen = recipe.get('joints') or {}
    meth = recipe.get('params', {}).get('method', 'cnc')
    for c in contacts:
        c['joint'] = pw.joint_for(meth, c['kind'], chosen.get(c['key']))
    return panels, contacts, skipped


def run_ply_fold(bodies, recipe):
    """Rozłóż płyty (flat=True) / Złóż płyty (flat=False). Płyty tylko się przesuwają i obracają, więc siatki są
    przekształcane, a nie liczone od nowa."""
    from . import plywood as pw
    ids = list(recipe['ids'])
    items = []
    for i in ids:
        b = _body(bodies, i)
        ply = (b.meta or {}).get('ply') or {}
        items.append(dict(id=b.id, shape=b.shape, t=ply.get('t'), fold=ply.get('fold')))
    moves, states = pw.fold_targets(items, bool(recipe['flat']), key=recipe.get('key'))
    if not moves:
        raise kernel.CadError('Płyty są już ' + ('rozłożone.' if recipe['flat'] else 'złożone (albo nigdy nie były rozkładane).'))
    out = []
    for b in bodies:
        m = moves.get(b.id)
        if m is None:
            out.append(b)
            continue
        shape = pw.apply_matrix(b.shape, m)
        meta = dict(b.meta or {})
        meta['ply'] = dict(meta.get('ply') or {}, fold=states[b.id])
        out.append(replace(b, shape=shape, mesh=kernel.mesh_moved(b.mesh, m) if b.mesh is not None else _deferred_or_mesh(shape),
                           meta=meta, threads=b.threads))
    return tuple(out)


def _deferred_or_mesh(shape):
    from .document import _mesh
    return _mesh(shape)


def run_ply_joints(bodies, recipe, failures=None):
    """Połączenia sklejki. Styk, którego nie da się połączyć, jest pomijany (reszta się wykonuje), a opis trafia do failures."""
    from . import plywood as pw
    panels, contacts, _ = ply_contacts(bodies, recipe)
    if not contacts:
        raise kernel.CadError('Płyty się nie stykają - nie ma czego połączyć.')
    params = recipe.get('params', {})
    failed = [] if failures is None else failures
    shapes = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, params, failed)
    bad = {key for key, _ in failed}
    if contacts and all(c['key'] in bad or c['joint'] == 'none' for c in contacts) and bad:
        raise kernel.CadError('Nie udało się wykonać żadnego połączenia: ' + failed[0][1])
    partners = {}
    for c in contacts:
        if c['joint'] != 'none' and c['key'] not in bad:
            partners.setdefault(c['a'], set()).add(c['b'])
            partners.setdefault(c['b'], set()).add(c['a'])
    out = []
    for b in bodies:
        if b.id in shapes or b.id in partners:
            ply = dict(b.meta['ply'])
            ply['method'] = params.get('method', ply.get('method', 'cnc'))
            ply['joined'] = sorted(set(ply.get('joined', ())) | partners.get(b.id, set()))
            nb = b.changed(shapes[b.id]) if b.id in shapes else b
            out.append(replace(nb, meta={**(b.meta or {}), 'ply': ply}))
        else:
            out.append(b)
    return out


def ply_joints_preview_job(bodies, recipe):
    """W procesie liczącym (osobny rdzeń): połączenia sklejki do podglądu - tylko zmienione płyty, razem z siatkami,
    żeby okno nie liczyło niczego samo."""
    from . import plywood as pw
    panels, contacts, _ = ply_contacts(bodies, recipe)
    if not contacts:
        return {}, []
    failed = []
    shapes = pw.apply_joints({p['id']: (p['shape'], p['n']) for p in panels}, contacts, recipe.get('params', {}), failed)
    return {pid: (shape, kernel.display_mesh(shape)) for pid, shape in shapes.items()}, failed


def ply_detect_job(bodies, ids):
    """W procesie liczącym: styki płyt (do listy połączeń) - bez kształtów w wyniku (lekkie do przesłania)."""
    from . import plywood as pw
    panels = pw.panels_of([b for b in bodies if b.id in set(ids)])
    contacts, skipped = pw.find_contacts(panels)
    light_contacts = [{k: v for k, v in c.items() if k != 'ends'} for c in contacts]
    return [p['id'] for p in panels], {p['id']: p['name'] for p in panels}, {p['id']: p['method'] for p in panels}, light_contacts, skipped


def run_multi(bodies, recipe):
    """Ta sama operacja na kilku zaznaczonych obiektach (lustro, szyk, przecięcie, skorupa...): kolejne kroki po kolei,
    jako jeden krok historii."""
    out = list(bodies)
    for step in recipe['steps']:
        out = list(run_recipe(out, step))
    return out


def run_folder(bodies, recipe):
    """Grupa (folder) na liście obiektów: przeniesienie do grupy, wyjęcie z niej (pusta nazwa) albo zmiana nazwy."""
    ids, folder = set(recipe['ids']), str(recipe.get('folder') or '')[:60]
    return [replace(b, folder=folder) if b.id in ids else b for b in bodies]


def run_sketchmeta(bodies, recipe):
    body = _body(bodies, recipe['id'])
    meta = recipe['meta']
    shape = meta_shape(body.plane, meta)
    return _replace(bodies, replace(body, shape=shape, mesh=kernel.display_mesh(shape), meta=meta))


def run_trim(bodies, recipe):
    """Nożyczki: usuwa kawałek szkicu (między przecięciami z innymi szkicami) najbliższy zapisanemu punktowi."""
    body = _body(bodies, recipe['id'])
    plane = kernel.actual_frame(body.shape, body.plane)
    group = sketch_groups(bodies).get(plane_key(plane))
    if group is None or body not in group[1]:
        raise kernel.CadError('Szkic nie jest już widoczny w tej płaszczyźnie.')
    members = group[1]
    pieces = kernel.trim_pieces([b.shape.Edges() for b in members], members.index(body))
    if not pieces:
        raise kernel.CadError('Brak kawałków do przycięcia.')
    mid = np.array(recipe['mid'], float)
    index = min(range(len(pieces)), key=lambda i: float(np.linalg.norm(np.array(pieces[i].positionAt(.5).toTuple()) - mid)))
    wires = kernel.trim_result(pieces, index)
    ids = pad_ids(recipe.get('out', ()), len(wires), (recipe.get('out') or [body.id])[0])
    made = [Body(body.name, w, 'sketch', body.plane, id=ids[i]).prepared() for i, w in enumerate(wires)]
    out = []
    for b in bodies:
        out.extend(made if b.id == body.id else [b])
    return merge_closed(out, plane)


def merge_closed(bodies, plane):
    """Otwarte kawałki szkiców w jednej płaszczyźnie, które razem tworzą zamknięty obrys, stają się jednym szkicem
    (na liście obiektów jedna pozycja). Nazwę i numer dostaje najstarszy z nich."""
    group = sketch_groups(bodies).get(plane_key(plane))
    if group is None:
        return bodies
    members = [b for b in group[1] if b.kind == 'sketch']
    joined = kernel.closed_groups([b.shape.Edges() for b in members])
    if not joined:
        return bodies
    replace_by, gone = {}, set()
    for indices in joined:
        parts = [members[i] for i in indices]
        try:
            wire = cq.Wire.assembleEdges([e for b in parts for e in b.shape.Edges()])
        except Exception:
            continue
        first = parts[0]
        replace_by[first.id] = replace(first, shape=wire, mesh=None, meta=None).prepared()
        gone |= {b.id for b in parts[1:]}
    return [replace_by.get(b.id, b) for b in bodies if b.id not in gone]


def place_bodies(bodies, ids, move=(0, 0, 0), rotate=(0, 0, 0)):
    """Przesuwa i obraca (wokół wspólnego środka) wskazane obiekty: edycja położenia obiektów dodanych w kroku bez przepisu."""
    ids = set(ids)
    group = [b for b in bodies if b.id in ids]
    if not group:
        return tuple(bodies)
    center = np.mean([b.shape.Center().toTuple() for b in group], axis=0)
    out = []
    for b in bodies:
        if b.id not in ids:
            out.append(b)
            continue
        shape = b.shape
        for axis, angle in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), rotate):
            if angle:
                shape = shape.rotate(tuple(float(c) for c in center), tuple(float(center[i] + axis[i]) for i in range(3)), float(angle))
        out.append(replace(b.changed(shape.translate(tuple(float(c) for c in move))), meta=None))
    return tuple(out)


RUNNERS = {'multi': run_multi, 'ply_panel': run_ply_panel, 'ply_wall': run_ply_wall, 'ply_between': run_ply_between, 'ply_joints': run_ply_joints, 'ply_fold': run_ply_fold, 'sheet_tabwall': run_sheet_tabwall, 'delete': run_delete, 'rename': run_rename, 'folder': run_folder, 'thread': run_thread, 'thread_real': run_thread_real, 'sketchmeta': run_sketchmeta, 'trim': run_trim, 'text': run_text, 'extrude': run_extrude, 'revolve': run_revolve, 'sweep': run_sweep, 'loft': run_loft, 'pattern': run_pattern, 'mod': run_mod, 'shell': run_shell, 'transform': run_transform, 'mirror': run_mirror, 'split': run_split, 'bool': run_bool, 'sheet': run_sheet, 'flange': run_flange, 'sheetbuild': run_sheetbuild, 'sheetmode':run_sheetmode, 'mate': run_mate}


_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow,
           ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
_FUNCTIONS = {'sqrt': math.sqrt, 'sin': lambda x: math.sin(math.radians(x)), 'cos': lambda x: math.cos(math.radians(x)),
              'tan': lambda x: math.tan(math.radians(x)), 'abs': abs, 'min': min, 'max': max, 'round': round}


def _decimal(text):
    text = str(text).strip()
    return text if re.search(r'\b(min|max|round)\s*\(', text) else text.replace(',', '.')


def evaluate(text, variables=None):
    """Bezpieczne wyliczenie wyrażenia (liczby, + - * / ** %, nawiasy, zmienne, sqrt / sin / cos / tan / abs / min / max / round, pi)."""
    names = dict(variables or {})
    names.setdefault('pi', math.pi)

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in names:
            return float(names[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return float(_BINARY[type(node.op)](walk(node.left), walk(node.right)))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return -walk(node.operand) if isinstance(node.op, ast.USub) else walk(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS and not node.keywords:
            return float(_FUNCTIONS[node.func.id](*[walk(a) for a in node.args]))
        raise ValueError(ast.dump(node)[:40])

    try:
        value = walk(ast.parse(_decimal(text), mode='eval'))
    except Exception as exc:
        raise kernel.CadError(f'Nieprawidłowe wyrażenie: {text}') from exc
    if not math.isfinite(value):
        raise kernel.CadError(f'Wyrażenie nie daje liczby: {text}')
    return value


def variable_values(variables):
    """Zmienne projektu (nazwa -> wyrażenie) policzone po kolei: późniejsze mogą korzystać z wcześniejszych."""
    out = {}
    for name, expr in (variables or {}).items():
        out[name] = evaluate(expr, out)
    return out


def has_expr(obj):
    if isinstance(obj, dict):
        return ('expr' in obj and len(obj) == 1) or any(has_expr(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(has_expr(v) for v in obj)
    return False


def resolve(obj, values):
    """Zamienia {'expr': '...'} w przepisie na liczby (według zmiennych projektu)."""
    if isinstance(obj, dict):
        if len(obj) == 1 and 'expr' in obj:
            return evaluate(obj['expr'], values)
        return {k: resolve(v, values) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [resolve(v, values) for v in obj]
    return obj


class Context:
    """Więzy, zmienne i znacznik zmiany zmiennych przekazywane do przeliczania."""

    def __init__(self, constraints=(), values=None, force=False):
        self.constraints, self.values, self.force = list(constraints or ()), dict(values or {}), force


def _ctx(value):
    return value if isinstance(value, Context) else Context(value or ())


def changed_ids(before, current):
    """Identyfikatory obiektów, które różnią się między dwoma stanami (inny kształt, widoczność, nazwa albo brak po jednej stronie)."""
    bm, cm = {b.id: b for b in before}, {b.id: b for b in current}
    return {i for i in bm.keys() | cm.keys()
            if i not in bm or i not in cm or bm[i].shape is not cm[i].shape or bm[i].visible != cm[i].visible or bm[i].name != cm[i].name}


def reads(recipe, current):
    """Zbiór obiektów, od których zależy wynik kroku (None = nie wiadomo, trzeba liczyć od nowa)."""
    kind = recipe['type']
    if kind == 'multi':
        ids = set()
        for step in recipe['steps']:
            got = reads(step, current)
            if got is None:
                return None
            ids |= got
        return ids
    sketches = {b.id for b in current if b.kind == 'sketch'}
    if kind in ('extrude', 'revolve', 'sweep', 'loft'):
        ids = set(recipe.get('spent', ()))
        if kind == 'sweep':
            ids.add(recipe['path']['id'])
        for spec in recipe['profiles']:
            if spec['k'] in ('region', 'textgroup'):
                ids |= sketches
            else:
                ids.add(spec['id'])
        return ids
    if kind == 'transform':
        return set(recipe.get('ids') or [recipe['id']])
    if kind == 'mod' and recipe.get('items'):
        return {item['id'] for item in recipe['items']}
    if kind in ('mod', 'shell', 'mirror', 'pattern', 'sketchmeta', 'rename', 'sheet', 'flange', 'sheetbuild', 'sheetmode'):
        return {recipe['id']}
    if kind == 'bool':
        return {recipe['base'], *recipe['tools']}
    if kind == 'mate':
        return {recipe['id'], recipe['target']}
    if kind == 'split':
        return {recipe['id'], *([recipe['tool']] if recipe.get('tool') else [])}
    if kind in ('delete', 'folder', 'ply_fold'):
        return set(recipe['ids'])
    if kind == 'sheet_tabwall':
        return None
    if kind == 'thread':
        return {item['id'] for item in recipe.get('items') or [recipe]}
    if kind == 'thread_real':
        return {recipe['id']}
    if kind == 'trim':
        return {recipe['id']} | sketches
    if kind == 'text':
        return set()
    if kind == 'ply_panel':
        ids = set(recipe.get('spent', ()))
        for spec in recipe['profiles']:
            ids |= sketches if spec['k'] in ('region', 'textgroup') else {spec['id']}
        return ids
    if kind == 'ply_between':
        return None                      # przycina się do innych płyt i nacina krzyżowo istniejące - zależy od wszystkich
    if kind == 'ply_joints':
        return set(recipe['ids'])
    return None


def run_recipe(bodies, recipe, values=None):
    if values is not None and has_expr(recipe):
        recipe = resolve(recipe, values)
    return tuple(RUNNERS[recipe['type']](bodies, recipe))


def diff_apply(old_prev, old_cur, new_prev):
    """Ogólny krok bez przepisu: przenosi różnicę (dodane / usunięte / zmienione obiekty) na nowy stan poprzedni.
    Zwraca (bryły, czy_się_udało)."""
    prev, cur = {b.id: b for b in old_prev}, {b.id: b for b in old_cur}
    merged = {b.id: b for b in new_prev}
    ok = True
    for i in prev:
        if i not in cur:
            merged.pop(i, None)
    for i, b in cur.items():
        if i not in prev:
            merged.setdefault(i, b)
            continue
        ob, nb = prev[i], merged.get(i)
        if nb is None:
            continue
        if b.shape is not ob.shape:
            if nb.shape is ob.shape:
                merged[i] = replace(nb, shape=b.shape, mesh=b.mesh, meta=b.meta, name=b.name, visible=b.visible, plane=b.plane)
            else:
                ok = False          # ten obiekt zmienił się na wcześniejszym kroku, a ten krok nie ma przepisu
            continue
        changes = {f: getattr(b, f) for f in ('name', 'visible', 'plane') if getattr(b, f) != getattr(ob, f)}
        if changes:
            merged[i] = replace(nb, **changes)
    order = [i for i in cur if i in merged] + [i for i in merged if i not in cur]
    return [merged[i] for i in order], ok


def meta_shape(plane, meta):
    t = meta['tool']
    pts = [tuple(p) for p in meta['points']]
    if t == 'line':
        return kernel.polyline(plane, pts, False)
    if t == 'arc':
        return kernel.arc3(plane, pts)
    if t == 'rect3':
        return kernel.rect3(plane, pts)
    return kernel.sketch_shape(t, plane, pts, meta.get('sides', 5))


def apply_constraints(bodies, constraints):
    """Więzy wymiarów: wymiar bi szkicu b = k * wymiar ai szkicu a albo = wyrażenie ze zmiennych projektu. Brak szkicu - więz pomijany."""
    ctx = _ctx(constraints)
    if not ctx.constraints:
        return tuple(bodies)
    bodies = list(bodies)
    for _ in range(len(ctx.constraints) + 1):      # kilka przebiegów: łańcuch więzów (A -> B -> C) ustala się niezależnie od kolejności
      changed = False
      for c in ctx.constraints:
          index = {b.id: i for i, b in enumerate(bodies)}
          if c['b'] not in index:
              continue
          b = bodies[index[c['b']]]
          if not (b.meta and b.meta.get('tool') in sm.EDITABLE):
              continue
          try:
              if 'expr' in c:
                  target = evaluate(c['expr'], ctx.values)
              else:
                  if c['a'] not in index:
                      continue
                  a = bodies[index[c['a']]]
                  if not (a.meta and a.meta.get('tool') in sm.EDITABLE):
                      continue
                  target = float(sm.values(a.meta)[c['ai']].replace(',', '.')) * float(c.get('k', 1.0))
              values = [float(x.replace(',', '.')) for x in sm.values(b.meta)]
              if abs(values[c['bi']] - target) < 1e-6:
                  continue
              values[c['bi']] = target
              meta = sm.apply_values(b.meta, values)
              shape = meta_shape(b.plane, meta)
              bodies[index[c['b']]] = Body(b.name, shape, b.kind, b.plane, b.id, b.visible, meta=meta).prepared()
              changed = True
          except Exception:
              continue
      if not changed:
        break
    return tuple(bodies)


def constraint_cycle(constraints):
    """True, gdy więzy wymiarów tworzą pętlę zależności (wymiar zależy od samego siebie przez inne)."""
    graph = {}
    for c in constraints:
        if 'a' in c:
            graph.setdefault((c['a'], c['ai']), set()).add((c['b'], c['bi']))
    state = {}

    def visit(node):
        state[node] = 1
        for nxt in graph.get(node, ()):
            if state.get(nxt) == 1 or (nxt not in state and visit(nxt)):
                return True
        state[node] = 2
        return False
    return any(node not in state and visit(node) for node in list(graph))


def rebuild(base, steps, constraints=(), job=None):
    ctx = _ctx(constraints)
    """Wykonuje kolejno kroki na stanie `base`. steps: lista (stan_przed_oryginalny, stan_po_oryginalny, info[, info_oryginalny]).
    Szybkie ścieżki: stan wejściowy nie zmienił się względem oryginału -> wynik oryginalny; krok niezależny od zmienionych obiektów ->
    przeniesienie różnicy bez ponownych obliczeń. Krok wyłączony ('off') niczego nie zmienia; nieprzeliczalny dostaje 'stale'.
    job: słownik {'cancel', 'i', 'n'} do przerywania i paska postępu. Zwraca (lista (bryły, info), liczba nieprzeliczonych)."""
    with kernel.deferred_mesh():          # stany pośrednie bez siatek: siatkuje się tylko stan, który potem widać
        return _rebuild(base, steps, ctx, job)


def _rebuild(base, steps, ctx, job):
    out, failed, current = [], 0, tuple(base)
    for n, step in enumerate(steps):
        before, after, info = step[:3]
        original = step[3] if len(step) > 3 else info
        if job is not None:
            if job.get('cancel'):
                raise kernel.CadError('Przeliczanie przerwane.')
            job['i'], job['n'] = n, len(steps)
        info = {key: v for key, v in info.items() if key != 'stale'}
        original = {key: v for key, v in original.items() if key != 'stale'}
        recipe = info.get('op')
        result, why = None, None
        diff = changed_ids(before, current)
        expr_step = bool(recipe) and ctx.force and has_expr(recipe)
        if info == original and not diff and not expr_step:
            result = tuple(after)
        elif info.get('off'):
            result = current
        elif recipe and recipe.get('type') in RUNNERS:
            dependencies = reads(recipe, current) if (info == original and not expr_step) else None
            if dependencies is not None and not (dependencies & diff):
                merged, ok = diff_apply(before, after, current)
                result = tuple(merged) if ok else None
            if result is None:
                try:
                    result = run_recipe(current, recipe, ctx.values)
                except Exception as exc:
                    result, why = None, str(exc) or exc.__class__.__name__
        else:
            merged, ok = diff_apply(before, after, current)
            result = tuple(merged) if ok else None
            if not ok:
                why = 'Ten krok zmienił obiekt, który wcześniej został zmieniony, a krok nie ma przepisu do ponownego wykonania.'
        info.pop('why', None)
        if result is None:
            failed += 1
            info['stale'] = True
            info['why'] = why or 'Nie udało się przeliczyć tego kroku.'
            result = current
        result = apply_constraints(result, ctx)
        out.append((result, info))
        current = result
    return out, failed


def _steps(states, indices):
    return [(states[j - 1][0], states[j][0], states[j][1]) for j in indices]


def recompute(states, k, edited_bodies, constraints=(), job=None):
    """Po edycji kroku k (jego nowy wynik: edited_bodies) przelicza kolejne kroki. Zwraca (nowe stany, liczba nieprzeliczonych kroków)."""
    edited_bodies = apply_constraints(edited_bodies, constraints)
    head = list(states[:k]) + [(tuple(edited_bodies), {key: v for key, v in states[k][1].items() if key not in ('stale', 'why')})]
    tail, failed = rebuild(edited_bodies, _steps(states, range(k + 1, len(states))), constraints, job)
    return head + tail, failed


def toggle_step(states, j, constraints=(), job=None):
    """Wyłącza / włącza krok j (stan go pomija) i przelicza resztę."""
    info = dict(states[j][1])
    if info.get('off'):
        info.pop('off')
    else:
        info['off'] = True
    steps = [(states[j - 1][0], states[j][0], info, states[j][1]), *_steps(states, range(j + 1, len(states)))]
    tail, failed = rebuild(states[j - 1][0], steps, constraints, job)
    return list(states[:j]) + tail, failed


def delete_step(states, j, constraints=(), job=None):
    """Usuwa krok j z osi czasu i przelicza następne."""
    tail, failed = rebuild(states[j - 1][0], _steps(states, range(j + 1, len(states))), constraints, job)
    return list(states[:j]) + tail, failed


def move_step(states, j, constraints=(), job=None):
    """Zamienia miejscami kroki j i j+1 (krok j przesuwa się później) i przelicza od j."""
    steps = [(states[j][0], states[j + 1][0], states[j + 1][1]), (states[j - 1][0], states[j][0], states[j][1]),
             *_steps(states, range(j + 2, len(states)))]
    tail, failed = rebuild(states[j - 1][0], steps, constraints, job)
    return list(states[:j]) + tail, failed


def recompute_all(states, constraints=(), job=None):
    """Pełne przeliczenie od pierwszego kroku (np. po zmianie zmiennej projektu): kroki z wyrażeniami liczone od nowa."""
    ctx = _ctx(constraints)
    ctx.force = True
    tail, failed = rebuild(states[0][0], _steps(states, range(1, len(states))), ctx, job)
    return [states[0], *tail], failed


_MOD_CACHE = {}          # w procesie roboczym: bryła i wycięty fragment ostatnio podglądanego zaokrąglenia


def mod_preview(shape, ids, points, size, kind, margin, cache=None):
    """Dokładny podgląd zaokrąglenia / fazy: tylko nowo powstała powierzchnia (siatka). Duża bryła -> mały fragment wokół zaznaczenia."""
    local_ids = ids
    try:
        if len(shape.Faces()) > 10:
            key = (None if ids is None else frozenset(ids),
                   None if points is None else tuple(tuple(np.round(q, 3)) for q in points), round(margin, 3))
            hit = cache.get('piece') if cache is not None else None
            if hit and hit[0] == key:
                piece, mapped = hit[1], hit[2]
            else:
                piece = kernel.local_piece(shape, ids, points, margin)
                mapped = None if (piece is None or points is not None) else kernel.map_edges(shape, piece, sorted(ids))
                if cache is not None:
                    cache['piece'] = (key, piece, mapped)
            if piece is not None and (points is not None or mapped is not None):
                shape, local_ids = piece, (None if points is not None else set(mapped))
    except Exception:
        local_ids = ids
    if points is not None:
        result = kernel.blend_vertices(shape, points, size, kind)
    else:
        result = kernel.blend(shape, local_ids, size, kind)
    made = kernel.new_faces(shape, result)
    return kernel.display_mesh(kernel.compound(made), .3) if made else kernel.display_mesh(result, .3)


def mod_preview_job(token, shape, ids, points, size, kind, margin):
    """W procesie roboczym. Bryłę wysyła się tylko raz (token); kolejne wartości przy przeciąganiu idą bez niej."""
    if shape is None:
        if _MOD_CACHE.get('token') != token:
            raise LookupError('brak bryły w pamięci procesu')
        shape = _MOD_CACHE['shape']
    elif _MOD_CACHE.get('token') != token:
        _MOD_CACHE.clear()
        _MOD_CACHE.update(token=token, shape=shape)
    return mod_preview(shape, ids, points, size, kind, margin, _MOD_CACHE)


# ---------- podglądy liczone w procesach roboczych (okno nie czeka na OpenCascade) ----------
def background(function, *args):
    """Zadanie podglądu w procesie roboczym; gdy procesów nie ma albo czegoś nie da się przesłać - tutaj (w wątku)."""
    from . import workers
    try:
        return workers.call_any(function, *args)
    except workers.Unavailable:
        return function(*args)


def light(bodies):
    """Bryły bez siatek - do przesłania do procesu (siatki są tam niepotrzebne, a ważą najwięcej)."""
    return [replace(b, mesh=None) for b in bodies]


def preview_meshes(makers, tol):
    """Siatki brył-narzędzi (wyciągnięcie, obrót, przeciągnięcie...): `makers` to funkcje z argumentami (functools.partial)."""
    return [kernel.display_mesh(make(), tol) for make in makers]


def mesh_of(function, args, tol):
    return kernel.display_mesh(function(*args), tol)


def split_preview(bodies, recipe, tol):
    parts = split_shapes(bodies, recipe)
    keep = recipe['keep']
    meshes = [(kernel.display_mesh(shape, tol), side, keep == 'both' or str(side) == keep) for shape, side in parts]
    cut = None
    if recipe['method'] in ('plane', 'face'):
        body = next(b for b in bodies if b.id == recipe['id'])
        n = np.array(recipe['normal'], float)
        n = n / np.linalg.norm(n)
        cut = kernel.display_mesh(kernel.cut_plane_face(body.shape, n, np.array(recipe['origin'], float) + n * recipe['offset'], 1.15))
    return meshes, cut


def recipe_body_mesh(bodies, recipe, tol):
    with kernel.deferred_mesh():
        moved = next(b for b in run_recipe(bodies, recipe) if b.id == recipe['id'])
    return kernel.display_mesh(moved.shape, tol)


def history_preview(bodies, recipe, values, tol):
    with kernel.deferred_mesh():       # potrzebne same kształty: podgląd ma własną, rzadszą siatkę
        result = run_recipe(bodies, recipe, values)
    return [kernel.display_mesh(b.shape, tol) for b in result if b.kind == 'solid' and b.visible]


def sweep_profile(src, path):
    return kernel.sweep_face(profile_outer(src), path)


def face_indices(shape, faces):
    """Numery ścian bryły - ściany przesłane osobno do procesu tracą powiązanie z bryłą, numery nie."""
    own = shape.Faces()
    out = []
    for face in faces:
        index = next((i for i, f in enumerate(own) if f.wrapped.IsSame(face.wrapped)), None)
        if index is None:
            raise kernel.CadError('Wybrana ściana nie należy już do bryły.')
        out.append(index)
    return out


def shell_indexed(shape, indices, thickness, inward):
    faces = shape.Faces()
    return kernel.shell_solid(shape, [faces[i] for i in indices], thickness, inward)
