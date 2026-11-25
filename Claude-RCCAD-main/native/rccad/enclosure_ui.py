"""Okno „Utwórz obudowę” (zakładka Obudowy) - etap 1 Generatora obudów: wybór elementów, układ współrzędnych,
przestrzeń zajmowana przez elementy z wymiarami X / Y / Z i tymczasowym podglądem.

Mixin okna Studio (tryb 'enclosure'). Korzysta z istniejących mechanizmów: zaznaczenie (lista Obiekty, klik w widoku),
podświetlenie (view.tints, warstwa najechania), podgląd (set_preview_mesh - nic nie trafia do dokumentu), nakładka
wymiarów widoku, run_operation + krok historii 'enclosure' (Cofnij / Ponów, zapis projektu). Elementy źródłowe nie są
zmieniane. Geometria i struktura danych: rccad.enclosure."""
from __future__ import annotations

import uuid

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton

from . import enclosure as enc
from . import kernel
from . import shell_ui as ui

SOURCE_TINT = (.30, .55, .95, 1)
PREVIEW_FILL = (.98, .62, .2, .16)
PREVIEW_LINE = (.9, .45, .05, 1)


def _label(text, name='label'):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class EnclosureTools:
    # ------------------------------------------------------------------ panel
    def _build_enclosure_panel(self):
        self.enc = dict(ids=[], face=None, picking_face=False, env=None, error=None)
        self.enc_panel, lay = self._panel(300, 'Utwórz obudowę', 'x_enclosure', 'Elementy → układ → obudowa', plain=True, scroll=True)
        self.enc_step1 = ui.StepRow(1, 'x_enclosure', 'Elementy w obudowie', plain=True)
        lay.addWidget(self.enc_step1)
        self.enc_list = QListWidget()
        self.enc_list.setObjectName('enclist')
        self.enc_list.setFixedHeight(104)
        self.enc_list.setStyleSheet('QListWidget#enclist { background:#ffffff; border:1px solid #d6e0ea; border-radius:8px; padding:2px; outline:0; }'
                                    ' QListWidget#enclist::item { padding:3px 6px; border-radius:6px; }'
                                    ' QListWidget#enclist::item:selected { background:#dcebfb; color:#17314a; }')
        self.enc_list.itemSelectionChanged.connect(lambda: self.enc_remove.setEnabled(bool(self.enc_list.selectedItems())))
        lay.addWidget(self.enc_list)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.enc_remove = QPushButton('Usuń z listy')
        self.enc_remove.setEnabled(False)
        self.enc_remove.clicked.connect(lambda _=False: self._enc_remove_selected())
        clear = QPushButton('Wyczyść')
        clear.clicked.connect(lambda _=False: self.enc_set_ids([]))
        row.addWidget(self.enc_remove)
        row.addWidget(clear)
        lay.addLayout(row)
        self.enc_step2 = ui.StepRow(2, 'x_axes', 'Układ współrzędnych', plain=True)
        lay.addWidget(self.enc_step2)
        self.enc_frame = QComboBox()
        for mode in enc.FRAME_MODES:
            self.enc_frame.addItem(enc.FRAME_LABELS[mode], mode)
        self.enc_frame.currentIndexChanged.connect(lambda *_: self._enc_frame_changed())
        lay.addWidget(self.enc_frame)
        self.enc_face_button = QPushButton('Wskaż ścianę orientacji')
        self.enc_face_button.setToolTip('Następne kliknięcie płaskiej ściany wyznaczy układ: Z - normalna ściany, X - jej najdłuższa krawędź')
        self.enc_face_button.clicked.connect(lambda _=False: self._enc_pick_face(True))
        lay.addWidget(self.enc_face_button)
        self.enc_dims = _label('Elementy: X —   Y —   Z —', 'value')
        self.enc_dims.setStyleSheet('font-weight:600; color:#17314a;')
        lay.addWidget(self.enc_dims)
        # --- etap 2: prostokątna obudowa ---
        self.enc_step3 = ui.StepRow(3, 'x_enclosure', 'Obudowa prostokątna', plain=True)
        lay.addWidget(self.enc_step3)
        self.enc_mode = QComboBox()
        for mode in enc.MODES:
            self.enc_mode.addItem(enc.MODE_LABELS[mode], mode)
        self.enc_mode.setCurrentIndex(self.enc_mode.findData('closed'))
        self.enc_mode.currentIndexChanged.connect(lambda *_: self._enc_params_changed())
        lay.addWidget(self.enc_mode)
        self.enc_clear, self.enc_clear_link = self._enc_grid(lay, 'Odstępy od elementów (mm)', enc.SIDES, 0.0, enc.DEFAULT_CLEARANCE)
        self.enc_wall, self.enc_wall_link = self._enc_grid(lay, 'Grubości ścianek (mm)', enc.WALLS, enc.MIN_WALL, enc.DEFAULT_WALL)
        self.enc_sizes = _label('Wnętrze: —\nZewnątrz: —', 'value')
        self.enc_sizes.setStyleSheet('font-weight:700; font-size:13px; color:#17314a;')
        lay.addWidget(self.enc_sizes)
        self.enc_status = _label('Klikaj bryły (także z importu STEP) - kliknięcie dodaje albo usuwa z listy.', 'status')
        lay.addWidget(self.enc_status)
        self.enc_apply, _ = self._buttons(self.enc_panel.footer, 'Zastosuj', 'Anuluj', self.apply_enclosure, lambda: self.set_mode(None))
        return self.enc_panel

    def _enc_grid(self, lay, title, keys, low, value):
        """Sześć pól (X−, X+, Y−, Y+, …) z przełącznikiem „Jednakowe” - jedna wartość dla wszystkich."""
        head = QHBoxLayout()
        head.addWidget(_label(title, 'label'), 1)
        link = QCheckBox('Jednakowe')
        link.setChecked(True)
        link.setToolTip('Wszystkie wartości powiązane jednym parametrem - zmiana jednej zmienia pozostałe')
        head.addWidget(link)
        lay.addLayout(head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        spins = {}
        for n, key in enumerate(keys):
            box = QDoubleSpinBox()
            box.setRange(low, enc.MAX_VALUE)          # wartości dające złą geometrię są zablokowane już w polu
            box.setDecimals(2)
            box.setSingleStep(.5)
            box.setValue(value)
            box.setButtonSymbols(QDoubleSpinBox.NoButtons)
            box.setKeyboardTracking(False)
            box.valueChanged.connect(lambda v, k=key, group=spins, l=link: self._enc_value_changed(group, l, k, v))
            grid.addWidget(_label(enc.SIDE_LABELS[key], 'label'), n // 2, (n % 2) * 2)
            grid.addWidget(box, n // 2, (n % 2) * 2 + 1)
            spins[key] = box
        lay.addLayout(grid)
        link.toggled.connect(lambda on, group=spins, k=keys[0]: on and self._enc_value_changed(group, link, k, group[k].value()))
        return spins, link

    def _enc_value_changed(self, group, link, key, value):
        if link.isChecked():
            for k, box in group.items():
                if k != key and box.isEnabled() and abs(box.value() - value) > 1e-12:
                    box.blockSignals(True)
                    box.setValue(value)
                    box.blockSignals(False)
        self._enc_params_changed()

    def _enc_params_changed(self):
        self.enc_wall['top'].setEnabled(self.enc_mode.currentData() != 'open')     # obudowa otwarta nie ma górnej ścianki
        self._enc_update()

    # ------------------------------------------------------------------ tryb
    def _enclosure_begin(self, previous=()):
        """set_mode('enclosure'): zaznaczone wcześniej bryły od razu na liście."""
        self.enc = dict(ids=[], face=None, picking_face=False, env=None, error=None)
        self.enc_frame.blockSignals(True)
        self.enc_frame.setCurrentIndex(0)
        self.enc_frame.blockSignals(False)
        self.enc_panel.show()
        self.enc_set_ids([i for i in previous if self._enc_ok(self.document.get(i))])
        self.hint('Utwórz obudowę: klikaj bryły, które mają być w obudowie (ponowne kliknięcie usuwa z listy).')
        self.view.setCursor(Qt.PointingHandCursor)

    def _enclosure_end(self):
        self.enc_items = []
        if hasattr(self, 'enc'):
            self.enc.update(env=None, picking_face=False)

    def _enc_ok(self, body):
        return body is not None and body.kind in enc.SOURCE_KINDS and body.visible and body.id not in self._eye_hidden()

    def enc_set_ids(self, ids):
        seen = []
        for i in ids:
            if i not in seen and self._enc_ok(self.document.get(i)):
                seen.append(i)
        self.enc['ids'] = seen
        self._enc_update()

    def enc_toggle(self, ids):
        """Klik w widoku / pozycja listy Obiekty: dodaje elementy (cała grupa), a gdy już są na liście - usuwa je."""
        ids = [i for i in ids if self._enc_ok(self.document.get(i))]
        if not ids:
            self.toast('Ta pozycja nie zawiera brył.')
            return
        current = list(self.enc['ids'])
        if all(i in current for i in ids):
            current = [i for i in current if i not in ids]
        else:
            current += [i for i in ids if i not in current]
        self.enc_set_ids(current)

    def _enc_remove_selected(self):
        drop = {item.data(Qt.UserRole) for item in self.enc_list.selectedItems()}
        self.enc_set_ids([i for i in self.enc['ids'] if i not in drop])

    def _enc_frame_changed(self):
        mode = self.enc_frame.currentData()
        self._enc_pick_face(mode == 'face' and self.enc['face'] is None)
        self._enc_update()

    def _enc_pick_face(self, on):
        self.enc['picking_face'] = bool(on)
        if on:
            if self.enc_frame.currentData() != 'face':
                self.enc_frame.blockSignals(True)
                self.enc_frame.setCurrentIndex(self.enc_frame.findData('face'))
                self.enc_frame.blockSignals(False)
            self.hint('Kliknij płaską ścianę, która wyznaczy orientację obudowy (Z - normalna ściany).')
        self._enc_update()

    # ------------------------------------------------------------------ widok
    def enclosure_hover(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        mesh = None
        if self.enc['picking_face']:
            if body is not None and body.kind == 'solid':
                try:
                    face, _n = self.view.face_at(body, hit)
                    if face is not None and kernel.is_planar_face(face):
                        mesh = kernel.display_mesh(face)
                except Exception:
                    mesh = None
        elif self._enc_ok(body):
            mesh = body.mesh
        if mesh is not getattr(self, '_enc_hover', None):
            self._enc_hover = mesh
            self.view.set_hover_mesh(mesh)

    def enclosure_click(self, x, y, shift=False):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if self.enc['picking_face']:
            if body is None or body.kind != 'solid':
                self.toast('Kliknij płaską ścianę bryły.')
                return
            try:
                origin, *_ = enc.face_frame(body.shape, hit[2])
            except kernel.CadError as exc:
                self.toast(str(exc))
                return
            self.enc['face'] = dict(id=body.id, point=[float(c) for c in origin], name=body.name)
            self.enc['picking_face'] = False
            self.view.set_hover_mesh(None)
            self._enc_hover = None
            self._enc_update()
            return
        if not self._enc_ok(body):
            self.toast('Kliknij bryłę (także zaimportowaną z pliku STEP).')
            return
        self.enc_toggle(self._group_ids(body.id))

    # ------------------------------------------------------------------ obliczenia i podgląd
    def enc_spec(self):
        """Bieżąca definicja obudowy (EnclosureSpec) z listy elementów i wybranego układu."""
        spec = enc.EnclosureSpec()
        for i in self.enc['ids']:
            b = self.document.get(i)
            if b is not None:
                spec.sources.append(enc.SourceRef(id=b.id, name=b.name, kind=b.kind, source=getattr(b, 'source', '')))
        mode = self.enc_frame.currentData()
        face = self.enc['face']
        spec.frame = enc.FrameSpec(mode=mode, face=dict(id=face['id'], point=face['point']) if (mode == 'face' and face) else None)
        spec.mode = self.enc_mode.currentData()
        spec.clearance = dict({k: float(b.value()) for k, b in self.enc_clear.items()}, linked=self.enc_clear_link.isChecked())
        spec.walls = dict({k: float(b.value()) for k, b in self.enc_wall.items()}, linked=self.enc_wall_link.isChecked())
        return spec

    def _enc_update(self):
        ids = self.enc['ids']
        self.enc_list.clear()
        for i in ids:
            b = self.document.get(i)
            tag = {'step': ' · STEP', 'stl': ' · STL'}.get(getattr(b, 'source', ''), '')
            item = QListWidgetItem(f'{b.name}{tag}')
            item.setData(Qt.UserRole, i)
            self.enc_list.addItem(item)
        self.enc_remove.setEnabled(False)
        self.enc_step1.set_state('done' if ids else 'active', f'{len(ids)} element(y)' if ids else 'kliknij bryły')
        mode = self.enc_frame.currentData()
        face = self.enc['face']
        self.enc_face_button.setVisible(mode == 'face')
        self.enc_face_button.setText('Kliknij płaską ścianę…' if self.enc['picking_face'] else
                                     ('Wskaż inną ścianę' if face else 'Wskaż ścianę orientacji'))
        self.enc_step2.set_state('done' if (mode != 'face' or face) else 'active',
                                 {'global': 'globalny', 'local': 'lokalny (OBB)'}.get(mode) or (f'ściana · {face["name"]}' if face else 'wskaż ścianę'))
        self.view.tints = {i: SOURCE_TINT for i in ids}          # elementy źródłowe podświetlone
        env, error = None, None
        if ids and (mode != 'face' or face):
            try:
                env = enc.envelope(self.document.bodies, self.enc_spec())
            except kernel.CadError as exc:
                error = str(exc)
            except Exception as exc:                  # nieoczekiwany kłopot geometrii - komunikat zamiast wyjątku
                error = f'Nie udało się wyznaczyć przestrzeni: {exc}'
        layout = None
        if env is not None:
            try:
                spec = self.enc_spec()
                layout = enc.box_layout(env, spec)
            except kernel.CadError as exc:
                error = str(exc)
        self.enc.update(env=env, error=error, layout=layout)
        self.enc_apply.setEnabled(layout is not None)       # niepoprawne wartości: Zastosuj zablokowane
        self.enc_step3.set_state('done' if layout is not None else ('active' if env is not None else 'pending'),
                                 self.enc_mode.currentText().split(' (')[0].lower() if layout is not None else (error or '') if env is not None else '')
        if env is not None:
            sx, sy, sz = env.size
            self.enc_dims.setText(f'Elementy: X {sx:.2f}   Y {sy:.2f}   Z {sz:.2f} mm')
        if layout is not None:
            i, o = layout['inner_size'], layout['outer_size']
            self.enc_sizes.setText(('Wnętrze: —' if spec.mode == 'solid' else f'Wnętrze: {i[0]:.2f} × {i[1]:.2f} × {i[2]:.2f}')
                                   + f'\nZewnątrz: {o[0]:.2f} × {o[1]:.2f} × {o[2]:.2f} mm')
            self.enc_status.setText('Enter albo Zastosuj dodaje obudowę jako nową bryłę (elementy zostają bez zmian).')
            self.enc_items = enc.outer_dimension_items(env, spec)
            self._enc_preview(env, spec)
        elif env is not None:
            self.enc_sizes.setText('Wnętrze: —\nZewnątrz: —')
            self.enc_status.setText(error)
            self.view.set_preview_mesh(None)
            self.enc_items = enc.dimension_items(env)
        else:
            self.enc_dims.setText('Elementy: X —   Y —   Z —')
            self.enc_sizes.setText('Wnętrze: —\nZewnątrz: —')
            self.enc_status.setText(error or ('Kliknij płaską ścianę orientacji.' if (ids and mode == 'face') else
                                              'Klikaj bryły (także z importu STEP) - kliknięcie dodaje albo usuwa z listy.'))
            self.view.set_preview_mesh(None)
            self.enc_items = []
        self.refresh()

    def _enc_preview(self, env, spec):
        """Podgląd obudowy (ta sama bryła co po Zastosuj) liczony w tle - nic nie trafia do dokumentu."""
        sig = repr(spec.to_json()) + repr(env.center) + repr(env.size)
        self._enc_sig = sig
        self.view.set_preview_mesh(kernel.display_mesh(enc.envelope_shape(env)), color=PREVIEW_FILL, line_color=PREVIEW_LINE, width=2, dashed=True)

        def compute():
            return kernel.display_mesh(enc.box_enclosure(env, spec))

        def show(mesh, error):
            if self.mode != 'enclosure' or getattr(self, '_enc_sig', None) != sig:
                return
            if error or mesh is None:
                self.enc_status.setText(str(error) if error else 'Nie udało się policzyć obudowy.')
                self.enc_apply.setEnabled(False)
                return
            self.view.set_preview_mesh(mesh, color=(.98, .62, .2, .32), line_color=PREVIEW_LINE, width=2)
        self.run_preview('enclosure', compute, show)

    # ------------------------------------------------------------------ zapis
    def apply_enclosure(self):
        """Zastosuj: definicja obudowy (elementy, układ, przestrzeń) jako obiekt „Obudowa” i krok historii - bez ścianek
        (ścianki - kolejny etap). Elementy źródłowe zostają bez zmian."""
        if self.busy or self.mode != 'enclosure':
            return
        if not self.enc['ids']:
            self.toast('Wybierz co najmniej jedną bryłę.')
            return
        if self.enc['env'] is None or self.enc.get('layout') is None:
            self.toast(self.enc['error'] or 'Wskaż ścianę orientacji.')
            return
        spec = self.enc_spec()
        count = 1 + sum(1 for b in self.document.bodies if b.kind == 'encl' or (b.meta or {}).get('enclosure'))
        recipe = dict(type='enclosure', spec=spec.to_json(), out=uuid.uuid4().hex, name=f'Obudowa {count}')
        existing = list(self.document.bodies)

        def build():
            return enc.run(existing, recipe)

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Obudowa prostokątna'
            self.document.pending_icon = 'enclosure'
            self.document.commit(bodies)

        def after():
            self.set_mode(None)
            if self.document.get(recipe['out']) is not None:
                self.selected = [recipe['out']]
                self.refresh()

        self.view.set_preview_mesh(None)
        self.run_operation('Obudowa prostokątna', build, apply, after=after)
