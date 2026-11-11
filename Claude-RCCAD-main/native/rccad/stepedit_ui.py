"""Edycja kroku historii tym samym narzędziem, którym krok powstał.

Mixin okna Studio. Dwuklik w symbol kroku (albo „Edytuj parametry…”) cofa model do stanu sprzed kroku i otwiera narzędzie
(Wyciągnięcie, Obrót, Zaokrąglenie / faza, Skorupa, Boolean, Kolor) z wartościami i wyborem z tego kroku. Zastosuj zastępuje
krok nowym wynikiem, a dalsze kroki przeliczają się w tle - tylko te, które zależą od zmienionych obiektów (reszta jest
przenoszona bez liczenia). Zamknij przywraca model do stanu sprzed edycji.

Krok rysowania szkicu (i zmiany jego wymiarów) otwiera szkic z tym kształtem zaznaczonym: uchwyty i Tab zmieniają wymiary,
zmiany wchodzą do tego samego kroku, a po wyjściu ze szkicu przeliczają się dalsze kroki.

Kroki bez własnego narzędzia (szyk, lustro, przesunięcie, tekst...) mają okno parametrów (history_edit_form)."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QTimer

from . import history as hist
from . import kernel
from . import sketchmeta as sm

TOOL_OF = {'extrude': 'extrude', 'revolve': 'revolve', 'mod': 'mod', 'shell': 'shell', 'bool': 'bool', 'color': 'color'}
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
        if self.hist_edit.isVisible():
            self._hist_edit_close()
        if kind in TOOL_OF and not (kind == 'shell' and recipe.get('steps')):
            return self._edit_with_tool(index, recipe)
        sketch = self._step_sketch(states, index)
        if sketch is not None and (kind is None or kind == 'sketchmeta'):
            return self._edit_sketch_step(index, sketch)
        return self.history_edit_form(index)

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

    def _edit_with_tool(self, index, recipe):
        kind = recipe['type']
        self._step_begin(index, index - 1)
        self.document.replace_next = True
        mode = TOOL_OF[kind]
        self._step_edit.update(mode=mode, recipe=recipe)
        try:
            self.set_mode(mode)
            getattr(self, '_step_fill_' + kind)(recipe)
        except Exception as exc:          # wybór z kroku nie pasuje do modelu: narzędzie zostaje otwarte puste
            self.toast(f'Nie udało się odtworzyć wyboru z kroku ({exc}) - wskaż elementy ponownie.', 5000)
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

    # ---------- koniec edycji (wywoływane z set_mode) ----------
    def _step_leaving(self, old_mode, new_mode):
        edit = self._step_edit
        if edit is None or old_mode != edit['mode'] or new_mode == old_mode:
            return
        self._step_edit = None
        doc = self.document
        if edit['mode'] == 'sketch':
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
        return None

    def _step_preview_hook(self, signals):
        timer = getattr(self, '_step_timer', None)
        if timer is None:
            timer = self._step_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(200)
            timer.timeout.connect(self._step_preview)
            for signal in signals:
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
        if recipe['type'] == 'revolve':
            return 'Obrót'
        return {'cut': 'Wycięcie', 'join': 'Wyciągnięcie (dodaj)', 'intersect': 'Część wspólna'}.get(recipe.get('mode'), 'Wyciągnięcie')
