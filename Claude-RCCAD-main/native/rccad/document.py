"""Immutable model revisions, atomic project files and undo/redo."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
from zipfile import ZipFile, ZIP_DEFLATED
import cadquery as cq
from .kernel import CadError, DisplayMesh, Frame, display_mesh, heavy, mesh_deferred, valid


def _mesh(shape):
    """Siatka nowej bryły - albo None w bloku kernel.deferred_mesh (uzupełni ją Document.meshed). Duża bryła dostaje najpierw
    zgrubną siatkę (widać ją od razu), a okno dolicza dokładną w tle (StudioWindow._refine_meshes)."""
    if mesh_deferred():
        return None
    from . import workers
    # zgrubna siatka tylko wtedy, gdy dokładną policzy osobny proces - inaczej liczyłaby się w oknie i je zacinała
    # (w samym procesie liczącym: zgrubna, bo dokładną dolicza potem okno w tle)
    return display_mesh(shape, coarse=(workers.ready() or workers.IN_WORKER) and heavy(shape))


@dataclass(frozen=True)
class Body:
    name: str
    shape: cq.Shape = field(compare=False, repr=False)
    kind: str = "solid"
    plane: object = "XY"   # 'XY' / 'XZ' / 'YZ' albo kernel.Frame (szkic na ścianie)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    visible: bool = True
    mesh: DisplayMesh | None = field(default=None, compare=False, repr=False)
    meta: dict | None = field(default=None, compare=False, repr=False)   # parametry szkicu (narzędzie, punkty, liczba boków) do edycji wymiarów
    group: str = field(default='', compare=False)       # wspólna grupa (np. szyk „jako jeden element”): zaznaczanie, wyciąganie i przenoszenie razem
    folder: str = field(default='', compare=False)      # grupa (folder) na liście obiektów - tylko porządek na liście, nie zmienia geometrii

    def prepared(self):
        return replace(self, mesh=_mesh(self.shape))

    def placed(self, shape, matrix):
        """Bryła po sztywnym przesunięciu / obrocie (macierz 3x4): blacha przenosi swój przepis razem z kształtem
        i dalej daje się rozkładać i zginać (zwykła zmiana kształtu - changed() - oznacza ją jako edytowaną)."""
        if self.kind == 'solid' and self.meta and self.meta.get('sheet'):
            from .sheetedit import placed_state
            return replace(self, shape=shape, mesh=_mesh(shape), meta=dict(self.meta, sheet=placed_state(self.meta['sheet'], matrix)))
        return self.changed(shape)

    def changed(self, shape, mesh=False):
        """Ta sama bryła z nowym kształtem. mesh: gotowa siatka (np. policzona w procesie liczącym); domyślnie liczona tutaj."""
        meta = None
        if self.kind == 'solid' and self.meta and self.meta.get('sheet'):
            meta = {'sheet': dict(self.meta['sheet'], dirty=True)}
        return replace(self, shape=shape, mesh=_mesh(shape) if mesh is False or (mesh is None and not mesh_deferred()) else mesh, meta=meta)


class Document:
    def __init__(self):
        self.bodies: tuple[Body, ...] = ()
        self._undo = []      # (bryły, rewizja, etykieta) stanów PRZED bieżącym
        self._redo = []
        self.info = {'label': 'Początek', 'icon': 'start'}
        self.constraints = []   # więzy wymiarów między szkicami: {a, ai, b, bi, k} - wymiar bi szkicu b = k * wymiar ai szkicu a
        self.variables = {}     # zmienne projektu: nazwa -> wyrażenie (liczone po kolei), używane w polach {'expr': ...}
        self.snapshots = {}   # warianty: nazwa -> dict(states, current, constraints, variables) - pełne osie czasu zapisane w projekcie
        self.backup = None   # poprzednia oś czasu sprzed edycji kroku historii (do cofnięcia edycji)
        self.path: Path | None = None
        self._revision = 0
        self._saved_revision = 0
        self._next_revision = 1
        self.pending_label = None
        self.pending_icon = None
        self.pending_op = None
        self._brep_cache = {}      # id(kształt) -> (kształt, bajty BREP): kolejne zapisy i autozapisy nie eksportują ponownie niezmienionej geometrii
        self._mesh_cache = {}      # id(kształt) -> (kształt, siatka): siatki wyświetlania liczone leniwie, tylko dla bieżącego stanu
        self.keep_future = False   # po przeskoku w historii nowa operacja wstawia się w środek, a późniejsze kroki są przeliczane
        self.deferred = None       # (stan sprzed wstawienia, późniejsze kroki) do przeliczenia w tle
        self.dropped = 0           # ile najstarszych kroków wypadło z historii (limit MAX_UNDO)

    MAX_UNDO = 999          # tyle kroków wstecz pamięta historia
    WARN_UNDO = 950         # od tylu kroków okno ostrzega, że najstarsze kroki zaczną znikać

    @property
    def history_length(self):
        return len(self._undo)

    @property
    def dirty(self):
        return self._revision != self._saved_revision

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def get(self, body_id):
        return next((b for b in self.bodies if b.id == body_id), None)

    @property
    def label(self):
        return self.info.get('label', '')

    @staticmethod
    def _auto_label(before, after):
        old, new = {b.id: b for b in before}, {b.id: b for b in after}
        added = [b for i, b in new.items() if i not in old]
        removed = [b for i, b in old.items() if i not in new]
        changed = [b for i, b in new.items() if i in old and (old[i].shape is not b.shape or old[i].visible != b.visible or old[i].name != b.name)]
        more = lambda xs: f' (+{len(xs) - 1})' if len(xs) > 1 else ''
        if added and not removed:
            return f'Dodano: {added[0].name}' + more(added), ('sketch' if added[0].kind == 'sketch' else 'file')
        if removed and not added:
            return f'Usunięto: {removed[0].name}' + more(removed), 'trash'
        if changed:
            return f'Zmieniono: {changed[0].name}' + more(changed), 'sketch' if changed[0].kind == 'sketch' else 'move'
        return 'Zmiana', 'move'

    def commit(self, bodies, label=None, icon=None, op=None):
        bodies = tuple(bodies)
        if len({b.id for b in bodies}) != len(bodies):
            raise CadError("Powtórzony identyfikator obiektu.")
        auto_label, auto_icon = self._auto_label(self.bodies, bodies)
        info = {'label': label or self.pending_label or auto_label, 'icon': icon or self.pending_icon or (auto_icon if not (label or self.pending_label) else 'move')}
        op = op or self.pending_op
        if op:
            info['op'] = op
        self._undo.append((self.bodies, self._revision, self.info))
        if len(self._undo) > self.MAX_UNDO:
            self.dropped += len(self._undo) - self.MAX_UNDO      # najstarsze kroki wypadają z historii (okno informuje o tym)
        self._undo = self._undo[-self.MAX_UNDO:]
        if self.keep_future and self._redo:
            self.deferred = (self.bodies, [(e[0], e[2]) for e in reversed(self._redo)])
        self.keep_future = False
        self._redo.clear()
        self.info = info
        self.pending_label = self.pending_icon = self.pending_op = None
        self.bodies = bodies
        self._revision = self._next_revision
        self._next_revision += 1

    def meshed(self, bodies):
        """Bryły z uzupełnionymi siatkami (stany historii wczytane z pliku nie mają siatek, dopóki nie zostaną pokazane)."""
        if all(b.mesh is not None for b in bodies):
            return tuple(bodies)
        todo = {}
        for b in bodies:
            if b.mesh is None:
                hit = self._mesh_cache.get(id(b.shape))
                if hit is None or hit[0] is not b.shape:
                    todo.setdefault(id(b.shape), b)
        if todo:
            # kilka brył naraz liczy się w procesach liczących (każda na innym rdzeniu), pojedyncza - tutaj
            from . import workers
            if len(self._mesh_cache) + len(todo) > 600:
                self._mesh_cache.clear()
            items = list(todo.values())
            for b, (mesh, error) in zip(items, workers.mesh_many([(b.shape, b.kind == 'solid') for b in items], coarse=True)):
                if error is not None:
                    raise CadError(error)
                self._mesh_cache[id(b.shape)] = (b.shape, mesh)
        out = []
        for b in bodies:
            if b.mesh is None:
                b = replace(b, mesh=self._mesh_cache[id(b.shape)][1])
            out.append(b)
        return tuple(out)

    def refined(self, shape, mesh):
        """Dokładna siatka policzona w tle zastępuje zgrubną: w bieżącym stanie i w pamięci siatek (bez nowego kroku historii)."""
        self._mesh_cache[id(shape)] = (shape, mesh)
        if any(b.shape is shape for b in self.bodies):
            self.bodies = tuple(replace(b, mesh=mesh) if b.shape is shape else b for b in self.bodies)
            return True
        return False

    def fine_mesh(self, shape):
        """Dokładna siatka z pamięci albo None."""
        hit = self._mesh_cache.get(id(shape))
        return hit[1] if hit is not None and hit[0] is shape and hit[1] is not None and hit[1].fine else None

    def append_states(self, tail):
        """Dokleja przeliczone późniejsze kroki za bieżący i ustawia widok na ostatnim."""
        states = self.states() + list(tail)
        self._set_states(states, len(states) - 1)

    def undo(self, mesh=True):
        self.keep_future = False
        if self._undo:
            self._redo.append((self.bodies, self._revision, self.info))
            self.bodies, self._revision, self.info = self._undo.pop()
            if mesh:
                self.bodies = self.meshed(self.bodies)

    def redo(self, mesh=True):
        self.keep_future = False
        if self._redo:
            self._undo.append((self.bodies, self._revision, self.info))
            self.bodies, self._revision, self.info = self._redo.pop()
            if mesh:
                self.bodies = self.meshed(self.bodies)

    # ---------- historia: oś czasu stanów (niezmienne bryły, więc przeskok jest natychmiastowy) ----------
    def timeline(self):
        """(etykiety, indeks bieżącego): stany od najstarszego do najnowszego, razem z cofniętymi (redo)."""
        from .history import step_label
        infos, current = self.infos()
        return [step_label(i) for i in infos], current

    def infos(self):
        return [e[2] for e in self._undo] + [self.info] + [e[2] for e in reversed(self._redo)], len(self._undo)

    def states(self):
        """Pełna oś czasu: lista (bryły, info) od pierwszego kroku."""
        return [(e[0], e[2]) for e in self._undo] + [(self.bodies, self.info)] + [(e[0], e[2]) for e in reversed(self._redo)]

    def rewrite(self, states, current, constraints=None, variables=None):
        """Podmienia całą oś czasu (po edycji kroku i przeliczeniu następnych); poprzednią (z więzami) zachowuje do cofnięcia edycji."""
        self.backup = (self.states(), len(self._undo), list(self.constraints), dict(self.variables))
        if constraints is not None:
            self.constraints = list(constraints)
        if variables is not None:
            self.variables = dict(variables)
        self._set_states(states, current)

    def set_info(self, index, **values):
        """Podpis / grupa kroku (bez zmiany geometrii i bez kopii zapasowej)."""
        states = self.states()
        bodies, info = states[index]
        info = dict(info)
        for key, value in values.items():
            if value:
                info[key] = value
            else:
                info.pop(key, None)
        states[index] = (bodies, info)
        self._set_states(states, len(self._undo))

    def clear_all(self):
        """Czyści całą pracę łącznie z historią (bez możliwości cofnięcia): pusta oś czasu, bez więzów, zmiennych i wariantów. Ścieżka pliku zostaje."""
        self.bodies = ()
        self._undo, self._redo = [], []
        self.info = {'label': 'Początek', 'icon': 'start'}
        self.constraints, self.variables, self.snapshots = [], {}, {}
        self.backup = None
        self.pending_label = self.pending_icon = self.pending_op = None
        self.keep_future, self.deferred = False, None
        self._mesh_cache.clear()
        self._revision = self._next_revision
        self._next_revision += 1

    def snapshot(self, name):
        """Zapamiętuje całą historię pod nazwą (wariant); bryły są niezmienne, więc kopia nic nie kosztuje."""
        self.snapshots[name] = dict(states=self.states(), current=len(self._undo), constraints=list(self.constraints), variables=dict(self.variables))
        self._revision = self._next_revision
        self._next_revision += 1

    def restore_snapshot(self, name):
        snap = self.snapshots[name]
        self.backup = (self.states(), len(self._undo), list(self.constraints), dict(self.variables))
        self.constraints, self.variables = list(snap['constraints']), dict(snap['variables'])
        self._set_states(list(snap['states']), snap['current'])

    def delete_snapshot(self, name):
        if self.snapshots.pop(name, None) is not None:
            self._revision = self._next_revision
            self._next_revision += 1

    def restore_backup(self):
        if self.backup:
            states, current, constraints, variables = self.backup
            self.backup = None
            self.constraints, self.variables = constraints, variables
            self._set_states(states, current)

    def _set_states(self, states, current):
        revisions = list(range(self._next_revision, self._next_revision + len(states)))
        self._next_revision += len(states)
        self._undo = [(b, revisions[i], inf) for i, (b, inf) in enumerate(states[:current])]
        self.bodies, self.info = states[current]
        self.bodies = self.meshed(self.bodies)
        self._redo = [(b, revisions[i], inf) for i, (b, inf) in reversed(list(enumerate(states))[current + 1:])]
        self._revision = revisions[current]
        self.keep_future, self.deferred = False, None

    def goto(self, index):
        labels, current = self.timeline()
        index = max(0, min(index, len(labels) - 1))
        while current > index:
            self.undo(False); current -= 1      # stany pośrednie nie są siatkowane: tylko docelowy
        while current < index:
            self.redo(False); current += 1
        self.bodies = self.meshed(self.bodies)
        self.keep_future = index < len(labels) - 1

    @staticmethod
    def _entry(body, shape_index):
        entry = dict(id=body.id, name=body.name, kind=body.kind, plane=body.plane, visible=body.visible, shape=shape_index)
        if body.group:
            entry['group'] = body.group
        if body.folder:
            entry['folder'] = body.folder
        if body.meta:
            entry['meta'] = body.meta
        if isinstance(body.plane, Frame):
            entry['plane'] = 'CUSTOM'
            entry['frame'] = body.plane.to_dict()
        return entry

    def _brep_bytes(self, shape, scratch):
        hit = self._brep_cache.get(id(shape))
        if hit is not None and hit[0] is shape:
            return hit[1]
        cq.exporters.export(shape, str(scratch), exportType="BREP")
        data = scratch.read_bytes()
        scratch.unlink()
        if len(self._brep_cache) > 3000:
            self._brep_cache.clear()
        self._brep_cache[id(shape)] = (shape, data)
        return data

    # Plik projektu (wersja 3): cała geometria w jednej paczce shapes.pack (BREP jeden za drugim, położenie w manifest['shapes']),
    # a w opisie kroków każdy obiekt (wpis) i każde dane blachy / szkicu (meta) zapisane raz - kroki tylko się do nich odwołują.
    # Dzięki temu długa historia nie tworzy tysięcy plików ani wielkiego manifestu. Wersje 1 i 2 nadal się wczytują.
    KEYFRAME = 10            # zapis kompaktowy: pełna geometria co tyle kroków (oraz bieżący krok i kroki bez przepisu)
    MAX_STATES = 1100
    MAX_SHAPES = 1_000_000
    MAX_MANIFEST = 200_000_000
    MAX_TOTAL = 4_000_000_000

    def _virtual_shapes(self, states, current):
        """Zapis kompaktowy: geometria kroków, które da się odtworzyć z przepisu, nie trafia do pliku (poza co KEYFRAME-tym
        krokiem, bieżącym i krokami bez przepisu). Zwraca id kształtów pomijanych."""
        from .history import RUNNERS
        must, introduced = set(), {}
        previous = set()
        for i, (bodies, info) in enumerate(states):
            ids = {id(b.shape) for b in bodies}
            op = info.get('op') or {}
            replayable = (i > 0 and i != current and i % self.KEYFRAME and op.get('type') in RUNNERS
                          and not info.get('off') and not info.get('stale'))
            if replayable:
                for key in ids - previous:
                    introduced.setdefault(key, i)
            else:
                must |= ids
            previous = ids
        return {key for key in introduced if key not in must}

    def save(self, path, mark=True, compact=False):
        """Zapisuje cały projekt razem z historią i wariantami. compact=True: lżejszy plik - część geometrii historii
        jest odtwarzana z przepisów przy otwieraniu (otwieranie trwa dłużej)."""
        path = Path(path)
        states = self.states()
        current = len(self._undo)
        virtual = self._virtual_shapes(states, current) if compact else set()
        shapes, index, vindex = [], {}, {}
        metas, meta_index, entries, entry_index = [], {}, [], {}
        manifest = {"app": "RCCAD_DESKTOP", "version": 3, "units": "mm", "pack": "shapes.pack", "shapes": [], "metas": metas,
                    "entries": entries, "states": [], "current": current, "constraints": self.constraints, "variables": self.variables}
        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(prefix=".rccad-", suffix=".tmp", dir=path.parent)
            os.close(fd)
            with tempfile.TemporaryDirectory(prefix="rccad-brep-") as work, ZipFile(temp_path, "w", ZIP_DEFLATED, allowZip64=True) as archive:
                with archive.open("shapes.pack", "w", force_zip64=True) as pack:
                    offset = 0

                    def shape_ref(shape, allow_virtual):
                        nonlocal offset
                        key = id(shape)
                        if allow_virtual and key in virtual:
                            if key not in vindex:
                                vindex[key] = len(vindex)
                            return -1 - vindex[key]
                        if key not in index:
                            index[key] = len(shapes)
                            shapes.append(shape)
                            data = self._brep_bytes(shape, Path(work) / "s.brep")
                            pack.write(data)
                            manifest['shapes'].append([offset, len(data)])
                            offset += len(data)
                        return index[key]

                    def emit(timeline, allow_virtual):
                        out = []
                        for i, (bodies, info) in enumerate(timeline):
                            refs, replay = [], False
                            for body in bodies:
                                ref = shape_ref(body.shape, allow_virtual)
                                replay = replay or ref < 0
                                entry = self._entry(body, ref)
                                if body.meta:
                                    text = json.dumps(body.meta, sort_keys=True, ensure_ascii=False)
                                    if text not in meta_index:
                                        meta_index[text] = len(metas)
                                        metas.append(body.meta)
                                    entry['meta'] = meta_index[text]
                                text = json.dumps(entry, sort_keys=True, ensure_ascii=False)
                                if text not in entry_index:
                                    entry_index[text] = len(entries)
                                    entries.append(entry)
                                refs.append(entry_index[text])
                            state = dict(label=info.get('label', ''), icon=info.get('icon', 'move'), op=info.get('op'), stale=bool(info.get('stale')),
                                         off=bool(info.get('off')), note=info.get('note'), group=info.get('group'), why=info.get('why'), bodies=refs)
                            if replay:
                                state['replay'] = True
                            out.append(state)
                        return out
                    manifest['states'] = emit(states, True)
                    manifest['snapshots'] = [dict(name=name, current=snap['current'], constraints=snap['constraints'], variables=snap['variables'], states=emit(snap['states'], False))
                                             for name, snap in self.snapshots.items()]
                    manifest['virtual'] = len(vindex)
                text = json.dumps(manifest, ensure_ascii=False)
                if len(text.encode('utf-8')) > self.MAX_MANIFEST or len(shapes) > self.MAX_SHAPES or offset > self.MAX_TOTAL:
                    raise CadError("Projekt przekracza dopuszczalny rozmiar (za długa historia). Zapisz wariant albo usuń stare kroki.")
                archive.writestr("manifest.json", text)
            os.replace(temp_path, path)
            if mark:      # autozapis (mark=False) nie zmienia ścieżki projektu ani stanu „zapisany”
                self.path = path
                self._saved_revision = self._revision
        finally:
            if temp_path and Path(temp_path).exists():
                Path(temp_path).unlink()

    @staticmethod
    def _parse_body(item, shape, mesh):
        identifier = str(item['id'])
        if not re.fullmatch('[0-9a-f]{32}', identifier):
            raise CadError("Nieprawidłowa struktura projektu.")
        kind = item.get('kind', 'solid')
        plane = item.get('plane', 'XY')
        if plane == 'CUSTOM' and kind == 'sketch':
            plane = Frame.from_dict(item['frame'])
        if kind not in ('solid', 'mesh', 'sketch') or not (isinstance(plane, Frame) or plane in ('XY', 'XZ', 'YZ')):
            raise CadError("Nieprawidłowy typ obiektu lub płaszczyzna.")
        meta = item.get('meta')
        group = item.get('group', '')
        group = group if isinstance(group, str) and re.fullmatch('[0-9a-f]{1,40}', group) else ''
        folder = item.get('folder', '')
        folder = folder.strip()[:60] if isinstance(folder, str) else ''
        return Body(str(item['name']), shape, kind, plane, identifier, bool(item.get('visible', True)), mesh=mesh,
                    meta=meta if isinstance(meta, dict) else None, group=group, folder=folder)

    @classmethod
    def load(cls, path):
        result = cls()
        try:
            with ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix="rccad-open-") as work:
                infos = archive.infolist()
                if sum(i.file_size for i in infos) > cls.MAX_TOTAL + cls.MAX_MANIFEST:
                    raise CadError("Projekt jest zbyt duży.")
                if archive.getinfo("manifest.json").file_size > cls.MAX_MANIFEST:
                    raise CadError("Nieprawidłowy manifest projektu.")
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get('app') != 'RCCAD_DESKTOP' or manifest.get('version') not in (1, 2, 3):
                    raise CadError("To nie jest obsługiwany projekt RCCAD Desktop.")
                if manifest['version'] in (1, 2) and len(infos) > 3001:
                    raise CadError("Projekt jest zbyt duży.")
                if manifest['version'] == 1:
                    if not isinstance(manifest.get('bodies'), list):
                        raise CadError("To nie jest obsługiwany projekt RCCAD Desktop.")
                    bodies, ids = [], set()
                    for item in manifest['bodies']:
                        identifier = str(item['id'])
                        if not re.fullmatch('[0-9a-f]{32}', identifier) or identifier in ids or item['file'] != f'bodies/{identifier}.brep':
                            raise CadError("Nieprawidłowa struktura projektu.")
                        ids.add(identifier)
                        source = Path(work) / (identifier + '.brep')
                        source.write_bytes(archive.read(item['file']))
                        shape = cq.importers.importBrep(str(source)).val()
                        valid(shape, item.get('kind', 'solid') == 'solid')
                        bodies.append(cls._parse_body(item, shape, None).prepared())
                    result.bodies = tuple(bodies)
                    result.path = Path(path)
                    return result
                version = manifest['version']
                files, states = manifest.get('shapes'), manifest.get('states')
                current = manifest.get('current')
                if not isinstance(files, list) or not isinstance(states, list) or not states or len(states) > cls.MAX_STATES or not isinstance(current, int) or not 0 <= current < len(states):
                    raise CadError("Nieprawidłowa struktura projektu.")
                pack = archive.read(manifest.get('pack', 'shapes.pack')) if version >= 3 else None
                metas = manifest.get('metas') or [] if version >= 3 else []
                table = manifest.get('entries') or [] if version >= 3 else []
                if version >= 3 and (not isinstance(metas, list) or not isinstance(table, list)):
                    raise CadError("Nieprawidłowa struktura projektu.")
                cache = {}      # numer geometrii -> (kształt, siatka): wczytywane i siatkowane raz, współdzielone przez wszystkie kroki

                def brep_bytes(number):
                    if version >= 3:
                        offset, size = files[number]
                        if not (isinstance(offset, int) and isinstance(size, int) and 0 <= offset and 0 < size and offset + size <= len(pack)):
                            raise CadError("Nieprawidłowa struktura projektu.")
                        return pack[offset:offset + size]
                    if files[number] != f'shapes/{number}.brep':
                        raise CadError("Nieprawidłowa struktura projektu.")
                    return archive.read(files[number])

                def geometry(number, kind):
                    if not isinstance(number, int) or not 0 <= number < len(files):
                        raise CadError("Nieprawidłowa struktura projektu.")
                    if number not in cache:
                        source = Path(work) / f'{number}.brep'
                        source.write_bytes(brep_bytes(number))
                        shape = cq.importers.importBrep(str(source)).val()
                        if shape is None or shape.wrapped.IsNull() or (kind == 'solid' and not shape.Solids()):      # pełna walidacja (isValid) przy pierwszym pokazaniu stanu
                            raise CadError("Nieprawidłowa geometria w projekcie.")
                        cache[number] = (shape, None)
                    return cache[number]

                def item_of(ref):
                    if version < 3:
                        return ref
                    if not isinstance(ref, int) or not 0 <= ref < len(table):
                        raise CadError("Nieprawidłowa struktura projektu.")
                    item = dict(table[ref])
                    if 'meta' in item:
                        m = item['meta']
                        if not isinstance(m, int) or not 0 <= m < len(metas):
                            raise CadError("Nieprawidłowa struktura projektu.")
                        item['meta'] = metas[m]
                    return item

                virtual = {}       # zapis kompaktowy: numer -> kształt odtworzony z przepisu kroku

                def replayed(state, previous, items):
                    """Kształty kroku zapisanego bez geometrii - wykonanie jego przepisu na poprzednim stanie."""
                    from .history import run_recipe
                    from .kernel import deferred_mesh
                    try:
                        with deferred_mesh():          # potrzebne same kształty
                            result = {b.id: b for b in run_recipe(previous, state['op'], {})}
                    except Exception:
                        result = {}
                    old = {b.id: b for b in previous}
                    missing = False
                    for item in items:
                        ref = item['shape']
                        if isinstance(ref, int) and ref < 0 and ref not in virtual:
                            body = result.get(str(item['id'])) or old.get(str(item['id']))
                            missing = missing or str(item['id']) not in result
                            if body is None:
                                raise CadError("Nie można odtworzyć historii projektu.")
                            virtual[ref] = (body.shape, None)
                    return missing

                def parse(state_list):
                  built = []
                  for state in state_list:
                      ids, bodies = set(), []
                      items = [item_of(ref) for ref in state['bodies']]
                      stale = False
                      if any(isinstance(item.get('shape'), int) and item['shape'] < 0 and item['shape'] not in virtual for item in items):
                          if not built or not isinstance(state.get('op'), dict):
                              raise CadError("Nieprawidłowa struktura projektu.")
                          stale = replayed(state, built[-1][0], items)
                      for item in items:
                          ref = item.get('shape')
                          shape, mesh = virtual[ref] if isinstance(ref, int) and ref < 0 else geometry(ref, item.get('kind', 'solid'))
                          body = cls._parse_body(item, shape, mesh)
                          if body.id in ids:
                              raise CadError("Nieprawidłowa struktura projektu.")
                          ids.add(body.id)
                          bodies.append(body)
                      info = {'label': str(state.get('label', 'Zmiana')), 'icon': str(state.get('icon', 'move'))}
                      if stale:
                          state = dict(state, stale=True, why='Nie udało się odtworzyć tego kroku z przepisu (zapis kompaktowy).')
                      if isinstance(state.get('op'), dict):
                          info['op'] = state['op']
                      if state.get('stale'):
                          info['stale'] = True
                      if state.get('off'):
                          info['off'] = True
                      for key in ('note', 'group', 'why'):
                          if isinstance(state.get(key), str) and state[key]:
                              info[key] = state[key][:80]
                      built.append((tuple(bodies), info))
                  return built

                built = parse(states)
                def parse_constraints(cons):
                    return [dict(b=str(c['b']), bi=int(c['bi']), expr=str(c['expr'])) if 'expr' in c else
                            dict(a=str(c['a']), ai=int(c['ai']), b=str(c['b']), bi=int(c['bi']), k=float(c.get('k', 1.0))) for c in cons if isinstance(c, dict)] if isinstance(cons, list) else []

                def parse_variables(variables):
                    return {str(k)[:40]: str(v)[:200] for k, v in variables.items()} if isinstance(variables, dict) else {}

                result.constraints = parse_constraints(manifest.get('constraints', []))
                result.variables = parse_variables(manifest.get('variables', {}))
                for snap in (manifest.get('snapshots') or [])[:30]:
                    if not isinstance(snap, dict) or not isinstance(snap.get('states'), list) or not 0 < len(snap['states']) <= cls.MAX_STATES:
                        continue
                    timeline = parse(snap['states'])
                    at = snap.get('current')
                    result.snapshots[str(snap.get('name', 'Wariant'))[:60]] = dict(
                        states=timeline, current=at if isinstance(at, int) and 0 <= at < len(timeline) else len(timeline) - 1,
                        constraints=parse_constraints(snap.get('constraints', [])), variables=parse_variables(snap.get('variables', {})))
                result._next_revision = 1
                revisions = list(range(1, len(built) + 1))
                result._next_revision = len(built) + 1
                result._undo = [(b, revisions[i], inf) for i, (b, inf) in enumerate(built[:current])]
                result.bodies, result.info = built[current]
                result.bodies = result.meshed(result.bodies)
                result._revision = result._saved_revision = revisions[current]
                result._redo = [(b, revisions[i], inf) for i, (b, inf) in reversed(list(enumerate(built))[current + 1:])]
                result.path = Path(path)
                return result
        except CadError:
            raise
        except Exception as exc:
            raise CadError("Nie można otworzyć projektu. Plik może być uszkodzony lub mieć inny format.") from exc
