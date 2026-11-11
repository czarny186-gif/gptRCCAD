"""Edycja kroku historii tym samym narzędziem, którym krok powstał.

Mixin okna Studio. Dwuklik w symbol kroku (albo „Edytuj parametry…”) cofa model do stanu sprzed kroku i otwiera narzędzie
(Wyciągnięcie, Obrót, Zaokrąglenie / faza, Skorupa, Boolean, Kolor) z wartościami i wyborem z tego kroku. Zastosuj zastępuje
krok nowym wynikiem, a dalsze kroki przeliczają się w tle - tylko te, które zależą od zmienionych obiektów (reszta jest
przenoszona bez liczenia). Zamknij przywraca model do stanu sprzed edycji.

Krok rysowania szkicu (i zmiany jego wymiarów) otwiera szkic z tym kształtem zaznaczonym: uchwyty i Tab zmieniają wymiary,
zmiany wchodzą do tego samego kroku, a po wyjściu ze szkicu przeliczają się dalsze kroki.

Wyciągnięcie, obrót, przeciągnięcie, loft, zaokrąglenie, skorupa, pochylenie, Boolean, kolor, szyk, lustro, cięcie, przesunięcie
i obrót (także otworu) otwierają się z wyborem i wartościami z kroku. Gwint, skalowanie, dopasowanie, tekst, blachy i sklejka
otwierają swoje narzędzie na modelu sprzed kroku - elementy wskazuje się ponownie. Nie ma osobnych, zastępczych okien edycji."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QTimer

from . import history as hist
from . import kernel
from . import sketchmeta as sm

TOOL_OF = {'extrude': 'extrude', 'revolve': 'revolve', 'mod': 'mod', 'shell': 'shell', 'bool': 'bool', 'color': 'color', 'tilt': 'tilt',
           'sweep': 'sweep', 'loft': 'loft', 'pattern': 'pattern', 'mirror': 'mirror', 'split': 'split',
           'transform': None, 'featmove': None}          # None: tryb z przepisu (move / rotate)
# narzędzia otwierane na modelu sprzed kroku bez odtworzenia wyboru - elementy wskazuje się ponownie, Zastosuj zastępuje krok
FRESH_OF = {'mate': None, 'thread': 'thread', 'thread_real': 'thread', 'scale': 'scale', 'sheet': 'sheet', 'flange': 'flange',
            'sheetbuild': 'flange', 'sheet_tabwall': 'tabwall', 'ply_panel': 'ply', 'ply_wall': 'ply_wall', 'ply_between': 'ply_between',
            'ply_joints': 'ply_joints', 'text': 'text'}
PREVIEW_TOL = .2


class StepEditTools:
    _step_edit = None

    # ---------- wejście w edycję ----------
    def history_edit(self, index):
        """Edycja kroku: to samo narzędzie co przy tworzeniu kroku (gdy jest), inaczej okno parametrów."""
        if self.busy:
            return
        states = self.document.states()
        if not 0 < index < len(states):
            return
        info = states[index][1]
        recipe = info.get('op') or {}
        kind = recipe.get('type')
        if kind in TOOL_OF:
            return self._edit_with_tool(index, recipe)
        sketch = self._step_sketch(states, index)
        if sketch is not None and (kind is None or kind == 'sketchmeta'):
            return self._edit_sketch_step(index, sketch)
        if kind in FRESH_OF:
            return self._edit_with_tool(index, recipe, fresh=True)
        added = [b.id for b in states[index][0] if b.id not in {x.id for x in states[index - 1][0]}]
        if kind is None and added:              # krok dodający obiekty (import, wstawienie z biblioteki): położenie w Przesuń
            return self._edit_added_step(index, added)
        self.toast('Ten krok nie ma własnego okna do zmiany (np. usunięcie, zmiana nazwy). Prawy przycisk na kroku: wyłącz, usuń albo przesuń krok.', 6000)

    @staticmethod
    def _step_sketch(states, index):
        """Szkic z wymiarami dodany (albo zmieniony) w tym kroku - albo None."""
        bodies, info = states[index]
        recipe = info.get('op') or {}
        if recipe.get('type') == 'sketchmeta':
            return next((b for b in bodies if b.id == recipe['id']), None)
        known = {b.id for b in states[index - 1][0]}
        added = [b for b in bodies if b.id not in known and b.kind == 'sketch' and b.meta and b.meta.get('tool') in sm.EDITABLE]
        return added[0] if added else None

    def _step_begin(self, index, at):
        """Model wraca do stanu `at` (przed krokiem albo po nim); dalsze kroki zostają za nim (przerywany obrys)."""
        if self.mode is not None:
            self.set_mode(None)
        back = self.document.infos()[1]
        self.document.goto(at)
        self.document.keep_future = True
        self._hist_trim = False
        self.selected, self.edges = [], {}
        self._step_edit = dict(index=index, back=back, mode=None)
        self.refresh()

    def _edit_with_tool(self, index, recipe, fresh=False):
        kind = recipe['type']
        self._step_begin(index, index - 1)
        self.document.replace_next = True
        mode = (FRESH_OF if fresh else TOOL_OF)[kind] or recipe.get('mode')
        if kind == 'text':
            mode = 'sketch'
        self._step_edit.update(mode=mode, recipe=recipe)
        try:
            if kind == 'text':
                self._step_fill_text(recipe)
            else:
                self.set_mode(mode)
                if not fresh:
                    getattr(self, '_step_fill_' + kind)(recipe)
        except Exception as exc:          # wybór z kroku nie pasuje do modelu: narzędzie zostaje otwarte puste
            self.toast(f'Nie udało się odtworzyć wyboru z kroku ({exc}) - wskaż elementy ponownie.', 5000)
            return
        if fresh and kind != 'text':
            self.toast(f'Edycja kroku {index}: wskaż elementy ponownie i kliknij Zastosuj - krok zostanie zastąpiony. Zamknij - bez zmian.', 7000)
        else:
            self.toast(f'Edycja kroku {index}: zmień ustawienia i kliknij Zastosuj (krok zostanie zastąpiony). Zamknij - bez zmian.', 6000)

    def _edit_sketch_step(self, index, sketch):
        self._step_begin(index, index)
        self.document.begin_merge()
        self._step_edit.update(mode='sketch', sketch=sketch.id)
        self.tool = None
        self.enter_sketch(sketch.plane)
        self.selected = [sketch.id]
        self.refresh()
        self._update_grips()
        self.sk_hint.setText('Edycja kroku: przeciągnij uchwyty albo Tab – wymiary. Wyjście ze szkicu przelicza dalsze kroki.')
        self.toast(f'Edycja kroku {index}: zmień kształt (uchwyty, Tab - wymiary). Wyjście ze szkicu zapisze zmianę i przeliczy dalsze kroki.', 7000)

    def _edit_added_step(self, index, ids):
        """Krok, który dodał obiekty bez przepisu: narzędzie Przesuń z tymi obiektami - nowe położenie wchodzi do tego kroku,
        a po zamknięciu narzędzia przeliczają się dalsze kroki."""
        self._step_begin(index, index)
        self.document.begin_merge()
        self._step_edit.update(mode='move')
        self.set_mode('move')
        body = self.document.get(ids[0])
        self.selected = list(ids)
        self.select_transform_target(body)
        self.toast(f'Edycja kroku {index}: przesuń / obróć dodane obiekty - zmiana zapisze się w tym kroku. Zamknij kończy edycję.', 7000)

    # ---------- koniec edycji (wywoływane z set_mode) ----------
    def _step_leaving(self, old_mode, new_mode):
        edit = self._step_edit
        if edit is None or old_mode != edit['mode'] or new_mode == old_mode:
            return
        self._step_edit = None
        doc = self.document
        if doc.merging:
            if doc.finish_merge():
                self._step_replayed = True
            else:
                QTimer.singleShot(0, lambda b=edit['back']: self._step_restore(b))
            return
        if doc.replace_next:              # narzędzie zamknięte bez Zastosuj: model wraca tam, gdzie był
            doc.replace_next = False
            QTimer.singleShot(0, lambda b=edit['back']: self._step_restore(b))
        else:
            self._step_replayed = True

    def _step_restore(self, back):
        if self.busy or self.mode is not None:
            return
        self.document.goto(back, mesh=False)
        self._show_state()

    @property
    def step_editing(self):
        return self._step_edit is not None

    # ---------- wypełnienie narzędzi wartościami z kroku ----------
    def _step_fill_extrude(self, recipe):
        self.ex_op.setCurrentIndex(['new', 'join', 'cut', 'intersect'].index(recipe['mode']))
        self.ex_dir.setCurrentIndex(['one', 'symmetric', 'two', 'ends'].index(recipe.get('dir', 'one')))
        self.ex_value.setValue(float(recipe['d1']))
        self.ex_second.setValue(float(recipe.get('d2', 0) or 0))
        self.ex_status.setText('Profile z edytowanego kroku. Zmień odległość lub operację i kliknij Zastosuj '
                               '(kliknięcie innego profilu wybiera profile od nowa).')
        self._step_preview_hook((self.ex_value.valueChanged, self.ex_second.valueChanged, self.ex_dir.currentIndexChanged, self.ex_op.currentIndexChanged))

    def _step_fill_revolve(self, recipe):
        self.rev_op.setCurrentIndex(['new', 'join', 'cut', 'intersect'].index(recipe['mode']))
        self.rev_angle.setValue(float(recipe.get('angle', 360)))
        self._step_preview_hook((self.rev_angle.valueChanged, self.rev_op.currentIndexChanged))

    def _step_fill_mod(self, recipe):
        kind_index = ['fillet', 'chamfer'].index(recipe['kind'])
        self.mod_kind.setCurrentIndex(kind_index)
        self.mod_size.setValue(float(recipe['size']))
        items = recipe.get('items') or [recipe]
        edges, verts = {}, {}
        for item in items:
            body = self.document.get(item['id'])
            if body is None:
                continue
            if item.get('edges'):
                edges[body.id] = set(hist.edge_indices(body.shape, item['edges']))
            if item.get('verts'):
                verts[body.id] = [np.asarray(q, float) for q in hist.vertex_points(body.shape, item)]
        self.edges, self.mod_vertices = edges, verts
        self.update_mod_status()

    def _step_fill_shell(self, recipe):
        body = self.document.get(recipe['id'])
        if body is None:
            raise kernel.CadError('brak bryły')
        faces = []
        for ref in recipe.get('faces', ()):
            face, normal = hist.match_face(body.shape, ref)
            faces.append(dict(face=face, normal=tuple(float(c) for c in normal), point=tuple(float(c) for c in face.Center().toTuple())))
        self.sh_id, self.sh_faces = body.id, faces
        self.sh_thick.setValue(float(recipe['thickness']))
        self.sh_dir.setCurrentIndex(0 if recipe.get('inward', True) else 1)
        self._sh_update()

    def _step_fill_bool(self, recipe):
        self.bool_op.setCurrentIndex(['union', 'subtract', 'intersect'].index(recipe['op']))
        self.bool_keep.setChecked(bool(recipe.get('keep')))
        self.bool_ids = [i for i in (recipe['base'], *recipe['tools']) if self.document.get(i) is not None]
        self.update_bool_status()

    def _step_fill_tilt(self, recipe):
        body = self.document.get(recipe['id'])
        if body is None:
            raise kernel.CadError('brak bryły')
        face = hist.match_face(body.shape, recipe['face'])[0]
        frame = hist.tilt_frame(body.shape, face)
        self.tl_face = dict(id=body.id, face=face, frame=frame, ref=recipe['face'], mesh=kernel.display_mesh(face))
        self.view.set_selection_meshes([self.tl_face['mesh']], color=(1, .55, .1, .35), line_color=(.95, .42, .02, 1))
        self._tl_set(recipe['heights'])

    def _step_fill_sweep(self, recipe):
        self.sw_op.setCurrentIndex(['new', 'join', 'cut', 'intersect'].index(recipe['mode']))
        self._step_preview_hook((self.sw_op.currentIndexChanged,))

    def _step_fill_loft(self, recipe):
        self.lf_op.setCurrentIndex(['new', 'join', 'cut', 'intersect'].index(recipe['mode']))
        self.lf_ruled.setCurrentIndex(1 if recipe.get('ruled') else 0)
        self._step_preview_hook((self.lf_op.currentIndexChanged, self.lf_ruled.currentIndexChanged))

    def _step_fill_mirror(self, recipe):
        body = self.document.get(recipe['id'])
        if body is None:
            raise kernel.CadError('brak obiektu')
        self.mirror_id = body.id
        self.mirror_frame = (tuple(float(c) for c in recipe['normal']), tuple(float(c) for c in recipe['origin']))
        self.mir_keep.setChecked(bool(recipe.get('keep')))
        self.mir_join.setChecked(bool(recipe.get('join')))
        self._tint_targets(body.id, ('solid', 'sketch'))
        self.update_mirror_status()

    def _step_fill_split(self, recipe):
        body = self.document.get(recipe['id'])
        if body is None:
            raise kernel.CadError('brak bryły')
        self.sp_id = body.id
        methods = ['plane', 'face', 'sketch', 'body']
        self.sp_method.setCurrentIndex(methods.index(recipe['method']))
        self.sp_keep.setCurrentIndex(['both', '1', '2'].index(str(recipe.get('keep', 'both'))))
        if recipe['method'] == 'plane':
            self.sp_plane.setCurrentIndex(['XY', 'XZ', 'YZ'].index(recipe.get('plane', 'XY')))
            self.sp_ref = None
        elif recipe['method'] == 'face':
            self.sp_ref = dict(normal=list(recipe['normal']), origin=list(recipe['origin']))
        else:
            tool = self.document.get(recipe['tool'])
            if tool is None:
                raise kernel.CadError('brak elementu tnącego')
            self.sp_ref = dict(tool=tool.id, name=tool.name)
        self.sp_offset.setValue(float(recipe.get('offset', 0.0)))
        self.update_split_status()

    def _step_fill_pattern(self, recipe):
        body = self.document.get(recipe['id'])
        if body is None:
            raise kernel.CadError('brak obiektu')
        p = recipe['params']
        kind = recipe['kind']
        self.pat_kind.setCurrentIndex(['rect', 'circ', 'path'].index(kind))
        self.pat_id = body.id
        self._tint_targets(body.id, ('solid', 'sketch'))
        axes = self._pattern_axes(body)
        if kind == 'rect':
            for i, axis in enumerate('XYZ'):
                self.pat_counts[i].setValue(int(p['counts'][i]))
                gap = float(p['spacing'][i])
                self.pat_gaps[i].setValue(abs(gap))
                for b in self.pat_dirs[i]:
                    b.setChecked((b.sign > 0) == (gap >= 0))
        elif kind == 'circ':
            key = max('XYZ', key=lambda a: abs(float(np.dot(axes[a], p['axis']))))
            self.pat_axis.setCurrentIndex(['Z', 'X', 'Y'].index(key))
            for spin, value in zip(self.pat_pivot, p['pivot']):
                spin.setValue(float(value))
            self.pat_ccount.setValue(int(p['count']))
            self.pat_angle.setValue(float(p['angle']))
            self.pat_radius.setValue(float(p.get('radius', 0)))
        else:
            self.pat_path = np.asarray(p['points'], float)
            self.pat_lcount.setValue(int(p['count']))
            self.pat_fit.setChecked(bool(p.get('fit', True)))
            self.pat_lgap.setValue(float(p.get('spacing', 20)))
        result = 'join' if recipe.get('join') else ('group' if recipe.get('group') else 'separate')
        self.pat_result.setCurrentIndex(['separate', 'group', 'join'].index(result))
        self.pat_join.setChecked(bool(recipe.get('join')))
        self.update_pattern_status()

    def _step_fill_transform(self, recipe):
        ids = [i for i in (recipe.get('ids') or [recipe['id']]) if self.document.get(i) is not None]
        if not ids:
            raise kernel.CadError('brak obiektu')
        self.selected = list(ids)
        self.select_transform_target(self.document.get(recipe['id']) or self.document.get(ids[0]))
        for spin, value in zip(self.t_spins, recipe['v']):
            spin.setValue(float(value))
        self.update_transform_preview()
        self._place_gizmo()

    def _step_fill_featmove(self, recipe):
        body = self.document.get(recipe['id'])
        if body is None:
            raise kernel.CadError('brak bryły')
        seed = hist.face_at_point(body.shape, recipe['point'])
        ids = hist.feature_faces(body.shape, seed) if seed is not None else None
        if not ids:
            raise kernel.CadError('otwór nie istnieje')
        filled, hole = hist.feature_split(body.shape, ids)
        box = kernel.bounds(hole)
        self.select_transform_target(body)
        self.t_feature = dict(id=body.id, point=list(recipe['point']), hole=hole, mesh=kernel.display_mesh(hole))
        self.t_center = self.t_mass = np.array(recipe.get('center') or box.center.toTuple(), float)
        self.t_radius = max(6.0, max(box.xlen, box.ylen, box.zlen) * 1.2)
        self.view.free_drag = None
        self.selected = []
        for spin, value in zip(self.t_spins, recipe['v']):
            spin.setValue(float(value))
        self.update_transform_preview()
        self._place_gizmo()

    def _step_fill_text(self, recipe):
        """Tekst: szkic na płaszczyźnie napisu z narzędziem Tekst i treścią, czcionką i wielkością z kroku."""
        plane = hist.plane_from_json(recipe['plane'])
        q = recipe.get('params') or {}
        if recipe.get('surface'):
            self.wrap_sketch = True
            self.surface_target = dict(recipe['surface'])
        self._text_plane_keep = True
        self.tool = None
        self.enter_sketch(plane)
        self.choose_tool('text')
        if q.get('text'):
            self.text_edit.setText(q['text'])
        if q.get('size'):
            self.text_size.setValue(float(q['size']))
        if self.txt is not None and q.get('anchor') is not None:
            self.txt.update(anchor=tuple(q['anchor']), size=float(q.get('size', self.txt['size'])), angle=float(q.get('angle', 0.0)))
            try:
                self._text_set_stage('edit')
                self._text_sync_spins()
            except Exception:
                pass

    def _step_fill_color(self, recipe):
        self.co_pending = {i: tuple(c) for i, c in (recipe.get('colors') or {}).items() if self.document.get(i) is not None}
        self._co_refresh()

    # ---------- Wyciągnięcie / Obrót bez nowego wyboru profili: przepis kroku z nowymi wartościami ----------
    def _step_recipe(self):
        """Przepis edytowanego kroku z wartościami z okna narzędzia (gdy profili nie wybrano od nowa) albo None."""
        edit = self._step_edit
        if edit is None or edit.get('recipe') is None or self.mode != edit['mode']:
            return None
        recipe = edit['recipe']
        if self.mode == 'extrude' and not self.ex_profiles:
            return dict(recipe, mode=self.ex_op.currentData(), dir=self.ex_dir.currentData(), d1=self.ex_value.value(), d2=self.ex_second.value())
        if self.mode == 'revolve' and not self.rev_profiles:
            return dict(recipe, mode=self.rev_op.currentData(), angle=self.rev_angle.value())
        if self.mode == 'sweep' and not self.sw_profiles:
            return dict(recipe, mode=self.sw_op.currentData())
        if self.mode == 'loft' and not self.lf_profiles:
            return dict(recipe, mode=self.lf_op.currentData(), ruled=self.lf_ruled.currentData() == 'ruled')
        return None

    def _step_preview_hook(self, signals):
        timer = getattr(self, '_step_timer', None)
        if timer is None:
            timer = self._step_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(200)
            timer.timeout.connect(self._step_preview)
            self._step_hooked = set()
        for signal in signals:          # każdy sygnał podłączany raz (narzędzia otwierane wielokrotnie)
            key = repr(signal)
            if key not in self._step_hooked:
                self._step_hooked.add(key)
                signal.connect(lambda *_: self._step_timer.start() if self._step_edit else None)
        timer.start()

    def _step_preview(self):
        recipe = self._step_recipe()
        if recipe is None:
            return
        base = list(self.document.bodies)
        from .studio import _merge_meshes

        def compute():
            solids = hist.background(hist.history_preview, hist.light(base), recipe, {}, PREVIEW_TOL)
            return _merge_meshes(solids) if solids else None

        def show(mesh, error):
            if self._step_recipe() is None:
                return
            if error or mesh is None:
                self.view.set_preview_mesh(None)
                if error:
                    self.toast(error)
                return
            red = recipe.get('mode') == 'cut'
            self.view.set_preview_mesh(mesh, color=(.9, .2, .2, .7) if red else (.18, .55, .9, .55), line_color=(.05, .2, .45, 1), width=2)

        self.run_preview('stepedit', compute, show)

    def apply_step_recipe(self):
        """Zastosuj w Wyciągnięciu / Obrocie podczas edycji kroku bez nowego wyboru profili. True - obsłużone."""
        recipe = self._step_recipe()
        if recipe is None:
            return False
        if self.busy:
            return True
        existing = list(self.document.bodies)
        label = self._step_label(recipe)

        def build():
            return list(hist.run_recipe(existing, recipe))

        def apply(new):
            self.document.pending_op = recipe
            self.document.commit(new)

        self.view.set_preview_mesh(None)
        self.view.set_handles([])
        self.run_operation(label, build, apply, after=lambda: self.set_mode(None))
        return True

    @staticmethod
    def _step_label(recipe):
        if recipe['type'] in ('revolve', 'sweep', 'loft'):
            return {'revolve': 'Obrót', 'sweep': 'Przeciągnięcie', 'loft': 'Wyciągnięcie złożone'}[recipe['type']]
        return {'cut': 'Wycięcie', 'join': 'Wyciągnięcie (dodaj)', 'intersect': 'Część wspólna'}.get(recipe.get('mode'), 'Wyciągnięcie')
