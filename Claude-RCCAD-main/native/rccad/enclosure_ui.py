"""Okno „Utwórz obudowę” (zakładka Obudowy) - Generator obudów.

Etap 1: wybór elementów, układ współrzędnych, przestrzeń zajmowana przez elementy (wymiary X / Y / Z, podgląd).
Etap 2: prostokątna obudowa B-Rep (odstępy, grubości ścianek, trzy rodzaje).
Etap 3: interaktywny podgląd - sześć strzałek na ścianach obudowy (odstępy / wymiary zewnętrzne / grubości ścianek),
        tryb symetryczny, wartości przy strzałkach z ręcznym wpisywaniem, przezroczystość, widoczność elementów,
        podświetlenie aktywnej ściany, przekrój podglądu. Podczas przeciągania - uproszczona siatka (bez OCC), po
        puszczeniu i po zmianie pól (z opóźnieniem) - dokładna bryła B-Rep w tle; nieaktualne wyniki są pomijane.
Etap 4: podział na podstawę i pokrywę (oś X / Y / Z, płaszczyzna bazowa, płaska ściana elementu), położenie w mm albo
        w %, strzałka płaszczyzny podziału, połączenia (płaskie, zakładka wewnętrzna / zewnętrzna, pióro i wpust),
        kontrola kolizji, widok złożony / rozstrzelony (tylko podgląd).

Mixin okna Studio (tryb 'enclosure'). Korzysta z istniejących mechanizmów: zaznaczenie (lista Obiekty, klik w widoku),
podświetlenie (view.tints, warstwa najechania), manipulatory (view.set_handles + handleDragged / handleReleased),
nakładka wymiarów (klik w wartość - pole edycji), podgląd (set_preview_mesh, run_preview - nic nie trafia do dokumentu),
przekrój widoku (set_section_plane), run_operation + krok historii 'enclosure' (Cofnij / Ponów, zapis projektu).
Elementy źródłowe nie są zmieniane. Geometria i struktura danych: rccad.enclosure."""
from __future__ import annotations

import uuid

import numpy as np

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from . import dims
from . import enclosure as enc
from . import kernel
from . import shell_ui as ui

SOURCE_TINT = (.30, .55, .95, 1)
PREVIEW_FILL = (.98, .62, .2, .16)
PREVIEW_LINE = (.9, .45, .05, 1)
PREVIEW_RGB = (.98, .62, .2)
HANDLE_COLOR = {'clearance': (.94, .6, .13, 1), 'outer': (.85, .35, .1, 1), 'walls': (.2, .5, .9, 1)}
SPLIT_COLOR = (.15, .65, .35, 1)
ACTIVE_WALL = (1.0, .55, .1, .45)
HANDLE_MODES = ('clearance', 'outer', 'walls')
HANDLE_LABELS = {'clearance': 'Odstępy od elementów', 'outer': 'Wymiary zewnętrzne', 'walls': 'Grubości ścianek'}
EXACT_DELAY_MS = 180            # zmiana pól: dokładna bryła dopiero po krótkiej przerwie (bez przeliczania przy każdym znaku)


def _label(text, name='label'):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def _spin(value, low, high, decimals=2, step=.5, suffix=''):
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    box.setButtonSymbols(QDoubleSpinBox.NoButtons)
    box.setKeyboardTracking(False)
    if suffix:
        box.setSuffix(suffix)
    return box


class EnclosureTools:
    # ------------------------------------------------------------------ panel
    def _build_enclosure_panel(self):
        self.enc = dict(ids=[], face=None, picking_face=False, picking_split=False, env=None, error=None)
        self._enc_timer = QTimer(self)
        self._enc_timer.setSingleShot(True)
        self._enc_timer.setInterval(EXACT_DELAY_MS)
        self._enc_timer.timeout.connect(lambda: self._enc_exact())
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
        # --- etap 3: manipulatory i podgląd ---
        lay.addWidget(_label('Strzałki na ścianach obudowy', 'label'))
        self.enc_handles = QComboBox()
        for mode in HANDLE_MODES:
            self.enc_handles.addItem(HANDLE_LABELS[mode], mode)
        self.enc_handles.setToolTip('Co zmienia przeciąganie strzałek i wartości przy nich (klik w wartość - wpisanie liczby)')
        self.enc_handles.currentIndexChanged.connect(lambda *_: self._enc_live(exact=False))
        lay.addWidget(self.enc_handles)
        self.enc_sym = QCheckBox('Symetrycznie')
        self.enc_sym.setToolTip('Strzałka albo wpisana wartość zmienia też przeciwną stronę - obudowa rośnie równo względem środka')
        lay.addWidget(self.enc_sym)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        grid.addWidget(_label('Przezroczystość', 'label'), 0, 0)
        self.enc_alpha = _spin(68, 0, 95, 0, 5, ' %')
        self.enc_alpha.setToolTip('Przezroczystość podglądu obudowy')
        self.enc_alpha.valueChanged.connect(lambda *_: self._enc_redisplay())
        grid.addWidget(self.enc_alpha, 0, 1)
        self.enc_inner = QCheckBox('Pokaż elementy w środku')
        self.enc_inner.setChecked(True)
        self.enc_inner.setToolTip('Widoczność elementów wewnętrznych (tylko w podglądzie - dokument się nie zmienia)')
        self.enc_inner.toggled.connect(lambda *_: self.refresh())
        grid.addWidget(self.enc_inner, 1, 0, 1, 2)
        self.enc_cut = QCheckBox('Przekrój podglądu')
        self.enc_cut.setToolTip('Tymczasowy przekrój obudowy i elementów płaszczyzną prostopadłą do wybranej osi')
        self.enc_cut.toggled.connect(lambda *_: self._enc_section())
        grid.addWidget(self.enc_cut, 2, 0)
        self.enc_cut_axis = QComboBox()
        for name in 'XYZ':
            self.enc_cut_axis.addItem(f'Oś {name}', name.lower())
        self.enc_cut_axis.setCurrentIndex(1)
        self.enc_cut_axis.currentIndexChanged.connect(lambda *_: self._enc_section())
        grid.addWidget(self.enc_cut_axis, 2, 1)
        grid.addWidget(_label('Położenie przekroju', 'label'), 3, 0)
        self.enc_cut_pos = _spin(0, -enc.MAX_VALUE, enc.MAX_VALUE, 2, 1, ' mm')
        self.enc_cut_pos.setToolTip('Odległość płaszczyzny przekroju od środka obudowy')
        self.enc_cut_pos.valueChanged.connect(lambda *_: self._enc_section())
        grid.addWidget(self.enc_cut_pos, 3, 1)
        lay.addLayout(grid)
        # --- etap 4: podział na podstawę i pokrywę ---
        self.enc_step4 = ui.StepRow(4, 'x_enclosure', 'Podstawa i pokrywa', plain=True)
        lay.addWidget(self.enc_step4)
        self.enc_split_on = QCheckBox('Podziel na podstawę i pokrywę')
        self.enc_split_on.toggled.connect(lambda *_: self._enc_split_changed())
        lay.addWidget(self.enc_split_on)
        self.enc_split_box = QWidget()
        box = QVBoxLayout(self.enc_split_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.enc_split_mode = QComboBox()
        for mode in enc.SPLIT_MODES:
            self.enc_split_mode.addItem(enc.SPLIT_LABELS[mode], mode)
        self.enc_split_mode.setCurrentIndex(self.enc_split_mode.findData('z'))
        self.enc_split_mode.currentIndexChanged.connect(lambda *_: self._enc_split_mode_changed())
        box.addWidget(self.enc_split_mode)
        self.enc_split_plane = QComboBox()
        for name in enc.PLANES:
            self.enc_split_plane.addItem(f'Płaszczyzna {name}', name)
        self.enc_split_plane.currentIndexChanged.connect(lambda *_: self._enc_split_changed())
        box.addWidget(self.enc_split_plane)
        self.enc_split_face = QPushButton('Wskaż płaską ścianę')
        self.enc_split_face.setToolTip('Następne kliknięcie płaskiej ściany wyznaczy płaszczyznę podziału')
        self.enc_split_face.clicked.connect(lambda _=False: self._enc_pick_split(True))
        box.addWidget(self.enc_split_face)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(_label('Położenie', 'label'))
        self.enc_split_pos = _spin(enc.SPLIT_DEFAULTS['position'], -enc.MAX_VALUE, enc.MAX_VALUE, 2, 1)
        self.enc_split_pos.setToolTip('mm: od dolnej ściany obudowy (osie) albo od wskazanej płaszczyzny / ściany; %: część wymiaru obudowy. '
                                      'Możesz też przeciągnąć zieloną strzałkę.')
        self.enc_split_pos.valueChanged.connect(lambda *_: self._enc_split_changed())
        row.addWidget(self.enc_split_pos, 1)
        self.enc_split_unit = QComboBox()
        self.enc_split_unit.addItem('mm', 'mm')
        self.enc_split_unit.addItem('%', '%')
        self.enc_split_unit.setCurrentIndex(1)
        self.enc_split_unit.currentIndexChanged.connect(lambda *_: self._enc_split_unit_changed())
        row.addWidget(self.enc_split_unit)
        box.addLayout(row)
        box.addWidget(_label('Połączenie podstawy i pokrywy', 'label'))
        self.enc_joint = QComboBox()
        for joint in enc.JOINTS:
            self.enc_joint.addItem(enc.JOINT_LABELS[joint], joint)
        self.enc_joint.currentIndexChanged.connect(lambda *_: self._enc_split_changed())
        box.addWidget(self.enc_joint)
        jg = QGridLayout()
        jg.setHorizontalSpacing(6)
        jg.setVerticalSpacing(5)
        self.enc_joint_spins = {}
        tips = {'width': 'Szerokość występu (w grubości ścianki)', 'height': 'Wysokość występu pokrywy',
                'depth': 'Głębokość gniazda w podstawie (co najmniej wysokość)', 'gap': 'Luz montażowy między występem a gniazdem'}
        for n, (key, title) in enumerate((('width', 'Szerokość'), ('height', 'Wysokość'), ('depth', 'Głębokość'), ('gap', 'Luz'))):
            spin = _spin(enc.SPLIT_DEFAULTS[key], 0.0 if key == 'gap' else .05, enc.MAX_VALUE, 2, .1)
            spin.setToolTip(tips[key])
            spin.valueChanged.connect(lambda *_: self._enc_split_changed())
            jg.addWidget(_label(title, 'label'), n // 2, (n % 2) * 2)
            jg.addWidget(spin, n // 2, (n % 2) * 2 + 1)
            self.enc_joint_spins[key] = spin
        box.addLayout(jg)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.enc_explode = QCheckBox('Widok rozstrzelony')
        self.enc_explode.setToolTip('Pokrywa odsunięta od podstawy tylko w podglądzie - położenie brył w dokumencie się nie zmienia')
        self.enc_explode.toggled.connect(lambda *_: self._enc_redisplay())
        row.addWidget(self.enc_explode, 1)
        self.enc_explode_dist = _spin(20, 0, enc.MAX_VALUE, 1, 5, ' mm')
        self.enc_explode_dist.valueChanged.connect(lambda *_: self._enc_redisplay())
        row.addWidget(self.enc_explode_dist)
        box.addLayout(row)
        lay.addWidget(self.enc_split_box)
        self.enc_split_box.setVisible(False)
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
            box = _spin(value, low, enc.MAX_VALUE)          # wartości dające złą geometrię są zablokowane już w polu
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
        self._enc_live()

    # ------------------------------------------------------------------ tryb
    def _enclosure_begin(self, previous=()):
        """set_mode('enclosure'): zaznaczone wcześniej bryły od razu na liście."""
        self.enc = dict(ids=[], face=None, picking_face=False, picking_split=False, env=None, error=None, split_face=None)
        self._enc_exact_result = None
        self.enc_frame.blockSignals(True)
        self.enc_frame.setCurrentIndex(0)
        self.enc_frame.blockSignals(False)
        for box in (self.enc_cut, self.enc_explode):
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
        self.enc_panel.show()
        self.enc_set_ids([i for i in previous if self._enc_ok(self.document.get(i))])
        self.hint('Utwórz obudowę: klikaj bryły, które mają być w obudowie (ponowne kliknięcie usuwa z listy).')
        self.view.setCursor(Qt.PointingHandCursor)

    def _enclosure_end(self):
        self.enc_items = []
        if hasattr(self, '_enc_timer'):
            self._enc_timer.stop()
        self._enc_exact_result = None
        if hasattr(self, 'enc'):
            had_cut = self.enc.get('section') is not None
            self.enc.update(env=None, picking_face=False, picking_split=False, section=None, drag=None)
            if had_cut:
                self._enc_section_restore()

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
            self.enc['picking_split'] = False
            if self.enc_frame.currentData() != 'face':
                self.enc_frame.blockSignals(True)
                self.enc_frame.setCurrentIndex(self.enc_frame.findData('face'))
                self.enc_frame.blockSignals(False)
            self.hint('Kliknij płaską ścianę, która wyznaczy orientację obudowy (Z - normalna ściany).')
        self._enc_update()

    def _enc_pick_split(self, on):
        self.enc['picking_split'] = bool(on)
        if on:
            self.enc['picking_face'] = False
            self.hint('Kliknij płaską ścianę elementu - wyznaczy płaszczyznę podziału obudowy.')
        self._enc_live(exact=False)

    # ------------------------------------------------------------------ widok
    def enclosure_hover(self, x, y):
        hid = self.view.hover_handle
        if hid and str(hid).startswith('enc:'):
            self._enc_highlight(hid)          # strzałka pod kursorem: podświetlona ściana, którą zmienia
            return
        if getattr(self, '_enc_active', None) is not None:
            self._enc_active = None
            self._enc_hover = None
            self.view.set_hover_mesh(None)
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        mesh = None
        if self.enc['picking_face'] or self.enc.get('picking_split'):
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
        if self.enc['picking_face'] or self.enc.get('picking_split'):
            if body is None or body.kind != 'solid':
                self.toast('Kliknij płaską ścianę bryły.')
                return
            try:
                face, _n = self.view.face_at(body, hit)
                if face is None or not kernel.is_planar_face(face):
                    raise kernel.CadError('Kliknij płaską ścianę bryły.')
                origin, *_ = enc.face_frame(body.shape, hit[2])
            except kernel.CadError as exc:
                self.toast(str(exc))
                return
            picked = dict(id=body.id, point=[float(c) for c in origin], name=body.name)
            self.view.set_hover_mesh(None)
            self._enc_hover = None
            if self.enc.get('picking_split'):
                self.enc['split_face'] = picked
                self.enc['picking_split'] = False
                self._enc_live()
                return
            self.enc['face'] = picked
            self.enc['picking_face'] = False
            self._enc_update()
            return
        if not self._enc_ok(body):
            self.toast('Kliknij bryłę (także zaimportowaną z pliku STEP).')
            return
        self.enc_toggle(self._group_ids(body.id))

    # ------------------------------------------------------------------ definicja
    def enc_spec(self):
        """Bieżąca definicja obudowy (EnclosureSpec) z listy elementów, układu i parametrów okna."""
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
        cut = self.enc.get('split_face')
        spec.split = dict(enabled=self.enc_split_on.isChecked(), mode=self.enc_split_mode.currentData(),
                          plane=self.enc_split_plane.currentData(), face=dict(id=cut['id'], point=cut['point']) if cut else None,
                          unit=self.enc_split_unit.currentData(), position=float(self.enc_split_pos.value()),
                          joint=self.enc_joint.currentData(), **{k: float(s.value()) for k, s in self.enc_joint_spins.items()})
        if self.enc.get('env') is not None:
            spec.envelope = self.enc['env']
        return spec

    # ------------------------------------------------------------------ obliczenia
    def _enc_update(self):
        """Pełna aktualizacja: lista elementów, układ, przestrzeń elementów (OCC - liczona tylko tu), potem parametry."""
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
        self.enc['env'] = None
        if ids and (mode != 'face' or face):
            try:
                env = enc.envelope(self.document.bodies, self.enc_spec())
            except kernel.CadError as exc:
                error = str(exc)
            except Exception as exc:                  # nieoczekiwany kłopot geometrii - komunikat zamiast wyjątku
                error = f'Nie udało się wyznaczyć przestrzeni: {exc}'
        self.enc.update(env=env, env_error=error)
        if env is not None:
            sx, sy, sz = env.size
            self.enc_dims.setText(f'Elementy: X {sx:.2f}   Y {sy:.2f}   Z {sz:.2f} mm')
        else:
            self.enc_dims.setText('Elementy: X —   Y —   Z —')
        self._enc_live(exact='now', refresh=False)
        self._enc_section()
        self.refresh()

    def _enc_live(self, exact=True, refresh=None):
        """Lekka aktualizacja po zmianie parametrów (pola, strzałki, wpisane wartości): układ obudowy, wymiary, strzałki,
        uproszczony podgląd (bez OCC). exact=True - dokładna bryła po krótkiej przerwie, 'now' - od razu, False - wcale
        (przeciąganie). Bez przebudowy modeli widoku - nawigacja zostaje płynna."""
        if not hasattr(self, 'enc') or self.mode != 'enclosure':
            return
        env = self.enc.get('env')
        ids = self.enc['ids']
        mode = self.enc_frame.currentData()
        face = self.enc['face']
        error = self.enc.get('env_error')
        spec = self.enc_spec()
        layout, plane = None, None
        if env is not None:
            try:
                layout = enc.box_layout(env, spec)
            except kernel.CadError as exc:
                error = str(exc)
        sp = enc.split_of(spec)
        split_error = None
        if layout is not None and sp['enabled']:
            try:
                plane = enc.split_check(env, spec, layout, self.document.bodies)
            except kernel.CadError as exc:
                split_error = str(exc)
        self.enc.update(error=error or split_error, layout=layout, plane=plane, split_error=split_error)
        ok = layout is not None and split_error is None and not self.enc.get('exact_error_sig') == self._enc_sig_of(spec)
        self.enc_apply.setEnabled(ok)       # niepoprawne wartości: Zastosuj zablokowane
        self.enc_step3.set_state('done' if layout is not None else ('active' if env is not None else 'pending'),
                                 self.enc_mode.currentText().split(' (')[0].lower() if layout is not None else (error or '') if env is not None else '')
        self._enc_split_widgets(sp)
        if sp['enabled']:
            self.enc_step4.set_state('done' if plane is not None else 'active', enc.JOINT_LABELS[sp['joint']].lower() if plane is not None else (split_error or ''))
        else:
            self.enc_step4.set_state('pending', 'bez podziału')
        if layout is not None:
            i, o = layout['inner_size'], layout['outer_size']
            self.enc_sizes.setText(('Wnętrze: —' if spec.mode == 'solid' else f'Wnętrze: {i[0]:.2f} × {i[1]:.2f} × {i[2]:.2f}')
                                   + f'\nZewnątrz: {o[0]:.2f} × {o[1]:.2f} × {o[2]:.2f} mm')
            kind = self.enc_handles.currentData()
            items = [] if kind == 'outer' else enc.outer_dimension_items(env, spec)
            self.enc_items = items + enc.side_dimension_items(env, spec, layout, kind)
            if split_error:
                self.enc_status.setText(split_error)
            elif self.enc.get('picking_split'):
                self.enc_status.setText('Kliknij płaską ścianę elementu - wyznaczy płaszczyznę podziału.')
            else:
                self.enc_status.setText('Przeciągnij strzałki albo kliknij wartość, aby ją wpisać. Enter albo Zastosuj dodaje '
                                        + ('podstawę i pokrywę' if sp['enabled'] else 'obudowę jako nową bryłę') + ' (elementy zostają bez zmian).')
            self._enc_handles(env, spec, layout, plane)
            self._enc_quick(env, spec)
            if exact == 'now':
                self._enc_timer.stop()
                self._enc_exact()
            elif exact:
                self._enc_timer.start()
        else:
            self.enc_sizes.setText('Wnętrze: —\nZewnątrz: —')
            self.view.set_handles([])
            self.view.show_custom_plane(None)
            self.view.set_preview_mesh(None)
            self._enc_shown = None
            self._enc_timer.stop()
            if env is not None:
                self.enc_status.setText(error)
                self.enc_items = enc.dimension_items(env)
            else:
                self.enc_status.setText(error or ('Kliknij płaską ścianę orientacji.' if (ids and mode == 'face' and not face) else
                                                  'Klikaj bryły (także z importu STEP) - kliknięcie dodaje albo usuwa z listy.'))
                self.enc_items = []
        if refresh is None:
            self.view.set_dims([*dims.view_items(self.document.bodies, self.selected), *self.enc_items])

    def _enc_split_widgets(self, sp):
        self.enc_split_box.setVisible(sp['enabled'])
        self.enc_split_plane.setVisible(sp['mode'] == 'plane')
        self.enc_split_face.setVisible(sp['mode'] == 'face')
        cut = self.enc.get('split_face')
        self.enc_split_face.setText('Kliknij płaską ścianę…' if self.enc.get('picking_split') else
                                    (f'Ściana: {cut["name"]} (wskaż inną)' if cut else 'Wskaż płaską ścianę'))
        joint = sp['joint'] != 'flat'
        for spin in self.enc_joint_spins.values():
            spin.setEnabled(joint)

    def _enc_sig_of(self, spec):
        return repr(spec.to_json())

    # ------------------------------------------------------------------ strzałki (manipulatory)
    def _enc_handles(self, env, spec, layout, plane):
        kind = self.enc_handles.currentData()
        size = float(np.max(layout['outer_size']))
        length = max(6.0, .18 * size)
        c, w = enc.clearance_of(spec), enc.walls_of(spec)
        handles = []
        for h in enc.side_handles(env, spec, layout):
            side = h['side']
            if kind == 'walls' and (spec.mode == 'solid' or (spec.mode == 'open' and side == 'z+')):
                continue
            handles.append(dict(id=f'enc:{side}', start=h['start'], tip=h['start'] + h['dir'] * length, dir=h['dir'],
                                color=HANDLE_COLOR[kind], label=enc.SIDE_LABELS[side], min_px=40))
        if plane is not None:
            point, n = plane[0], plane[1]
            centre = np.asarray(env.center, float)
            p0 = centre - float((centre - point) @ n) * n          # środek obudowy rzutowany na płaszczyznę podziału
            axes = np.asarray(env.axes, float)
            i = int(np.argmin([abs(float(a @ n)) for a in axes]))   # strzałka podziału z boku - nie zasłania strzałek ścian
            side = axes[i] - float(axes[i] @ n) * n
            if np.linalg.norm(side) > 1e-9:
                p0 = p0 + side / np.linalg.norm(side) * .3 * float(layout['outer_size'][i])
            handles.append(dict(id='enc:split', start=p0, tip=p0 + n * length * 1.2, dir=n, color=SPLIT_COLOR, label='Podział', min_px=54))
            self.view.show_custom_plane(kernel.face_frame(p0, n), half=.62 * float(np.linalg.norm(layout['outer_size'])),
                                        color=SPLIT_COLOR[:3])
        else:
            self.view.show_custom_plane(None)
        self.view.set_handles(handles)
        drag = self.enc.get('drag')
        if drag is not None or (self.view.hover_handle and str(self.view.hover_handle).startswith('enc:')):
            self._enc_highlight(drag['id'] if drag else self.view.hover_handle, force=True)

    def _enc_highlight(self, hid, force=False):
        """Podświetlenie ściany, którą zmienia strzałka (osobna warstwa najechania - bez przebudowy modeli)."""
        if hid == getattr(self, '_enc_active', None) and not force:
            return
        self._enc_active = hid
        mesh = None
        side = str(hid)[4:]
        layout, env = self.enc.get('layout'), self.enc.get('env')
        if side in enc.SIDES and layout is not None and env is not None:
            mesh = enc.wall_slab(env, self.enc_spec(), layout, side)
        self._enc_hover = mesh
        self.view.set_hover_mesh(mesh, color=ACTIVE_WALL, line_color=(.95, .42, .02, 1), width=2.6)

    def _enc_unlink(self, group, link, name):
        if link.isChecked():
            link.blockSignals(True)
            link.setChecked(False)
            link.blockSignals(False)
            self.toast(f'{name}: strzałka zmienia jedną stronę - „Jednakowe” wyłączone.')

    def enc_handle_dragged(self, hid, delta):
        """Przeciąganie strzałki: zmienia odstęp / grubość tylko po tej stronie (pozostałe ściany stoją), w trybie
        symetrycznym także po przeciwnej. Pola liczbowe idą za strzałką na żywo, podgląd uproszczony."""
        if self.mode != 'enclosure' or self.enc.get('layout') is None:
            return
        drag = self.enc.get('drag')
        if drag is None or drag['id'] != hid:
            drag = self.enc['drag'] = dict(id=hid, clear={k: b.value() for k, b in self.enc_clear.items()},
                                           wall={k: b.value() for k, b in self.enc_wall.items()}, pos=self.enc_split_pos.value())
            if hid != 'enc:split':
                if self.enc_handles.currentData() == 'walls':
                    self._enc_unlink(self.enc_wall, self.enc_wall_link, 'Grubości ścianek')
                else:
                    self._enc_unlink(self.enc_clear, self.enc_clear_link, 'Odstępy')
        if hid == 'enc:split':
            plane = self.enc.get('plane')
            if plane is None:
                return
            lo, hi = plane[2]
            step = delta if self.enc_split_unit.currentData() == 'mm' else delta / max(hi - lo, 1e-9) * 100.0
            self._enc_set(self.enc_split_pos, round(drag['pos'] + step, 2))
            self._enc_live(exact=False)
            return
        side = hid[4:]
        if side not in enc.SIDES:
            return
        sides = [side, enc.OPPOSITE[side]] if self.enc_sym.isChecked() else [side]
        if self.enc_handles.currentData() == 'walls':
            for s in sides:
                key = enc.WALL_OF[s]
                if self.enc_wall[key].isEnabled():
                    self._enc_set(self.enc_wall[key], max(enc.MIN_WALL, round(drag['wall'][key] + delta, 1)))
        else:
            for s in sides:
                self._enc_set(self.enc_clear[s], max(0.0, round(drag['clear'][s] + delta, 1)))
        self._enc_live(exact=False)

    def enc_handle_released(self, hid):
        """Koniec ruchu: dokładna bryła B-Rep od razu (w tle)."""
        self.enc['drag'] = None
        self._enc_live(exact='now')

    @staticmethod
    def _enc_set(spin, value):
        spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(False)

    def enc_value_entered(self, cid, value):
        """Wartość wpisana przy strzałce (klik w wymiar): odstęp, grubość ścianki albo wymiar zewnętrzny X / Y / Z."""
        key = cid.split(':', 1)[1]
        sym = self.enc_sym.isChecked()
        layout = self.enc.get('layout')
        if layout is None:
            return
        if key in ('X', 'Y', 'Z'):
            i = 'XYZ'.index(key)
            delta = value - float(layout['outer_size'][i])
            plus, minus = enc.SIDES[2 * i + 1], enc.SIDES[2 * i]
            values = {k: b.value() for k, b in self.enc_clear.items()}
            if sym:
                values[plus] += delta / 2
                values[minus] += delta / 2
            else:
                values[plus] += delta
            if min(values[plus], values[minus]) < -1e-9:
                cp, cm = self.enc_clear[plus].value(), self.enc_clear[minus].value()
                least = float(layout['outer_size'][i]) - (2 * min(cp, cm) if sym else cp)
                self.toast(f'Najmniejszy wymiar zewnętrzny {key} przy tych grubościach to {least:.2f} mm (odstęp nie może być ujemny).')
                return
            self._enc_unlink(self.enc_clear, self.enc_clear_link, 'Odstępy')
            for k in (plus, minus):
                self._enc_set(self.enc_clear[k], max(0.0, values[k]))
        elif key in enc.SIDES:
            sides = [key, enc.OPPOSITE[key]] if sym else [key]
            if self.enc_handles.currentData() == 'walls':
                if value < enc.MIN_WALL:
                    self.toast(f'Grubość ścianki musi być co najmniej {enc.MIN_WALL:g} mm.')
                    return
                for s in sides:
                    box = self.enc_wall[enc.WALL_OF[s]]
                    if box.isEnabled():
                        box.setValue(value)            # zwykła zmiana pola („Jednakowe” działa jak przy wpisywaniu w pole)
            else:
                if value < 0:
                    self.toast('Odstęp nie może być ujemny.')
                    return
                for s in sides:
                    self.enc_clear[s].setValue(value)
        else:
            return
        self._enc_live(exact='now')

    # ------------------------------------------------------------------ podział (etap 4)
    def _enc_split_changed(self):
        self._enc_live()

    def _enc_split_mode_changed(self):
        mode = self.enc_split_mode.currentData()
        if mode == 'face' and self.enc.get('split_face') is None:
            self._enc_pick_split(True)
            return
        if mode != 'face':
            self.enc['picking_split'] = False
        self._enc_live()

    def _enc_split_unit_changed(self):
        """mm ↔ %: wartość przeliczona tak, żeby płaszczyzna podziału została w tym samym miejscu."""
        plane = self.enc.get('plane')
        unit = self.enc_split_unit.currentData()
        if plane is not None:
            lo, hi = plane[2]
            d = plane[3]
            axis = self.enc_split_mode.currentData() in ('x', 'y', 'z')
            value = (d - lo) / max(hi - lo, 1e-9) * 100.0 if unit == '%' else (d - lo if axis else d)
            self._enc_set(self.enc_split_pos, round(value, 2))
        self._enc_live()

    # ------------------------------------------------------------------ podgląd
    def _enc_alpha(self):
        return max(.05, 1.0 - self.enc_alpha.value() / 100.0)

    def _enc_quick(self, env, spec):
        """Uproszczony podgląd (siatka bez OCC) - od razu przy każdej zmianie; dokładny zastąpi go, gdy będzie gotowy."""
        sig = self._enc_sig_of(spec)
        result = getattr(self, '_enc_exact_result', None)
        if result is not None and result['sig'] == sig:
            self._enc_redisplay()
            return
        try:
            explode = self.enc_explode_dist.value() if self.enc_explode.isChecked() else 0.0
            mesh = enc.quick_mesh(env, spec, explode)
        except kernel.CadError:
            mesh = None
        self._enc_shown = ('quick', sig)
        self.view.set_preview_mesh(mesh, color=(*PREVIEW_RGB, self._enc_alpha() * .7), line_color=PREVIEW_LINE, width=1.6, dashed=True)

    def _enc_exact(self):
        """Dokładna bryła B-Rep w tle (run_preview: ostatnie żądanie wygrywa); wynik pokazany tylko, gdy parametry się od
        tego czasu nie zmieniły (podpis) i nie trwa przeciąganie."""
        if self.mode != 'enclosure' or self.enc.get('layout') is None or self.enc.get('split_error'):
            return
        env = self.enc['env']
        spec = self.enc_spec()
        sig = self._enc_sig_of(spec)
        result = getattr(self, '_enc_exact_result', None)
        if result is not None and result['sig'] == sig:
            self._enc_redisplay()
            return
        self._enc_sig = sig
        bodies = list(self.document.bodies)
        split = enc.split_of(spec)['enabled']

        def compute():
            if split:
                parts = enc.split_enclosure(env, spec, bodies, check_sources=True)
                return dict(base=kernel.display_mesh(parts['base']), lid=kernel.display_mesh(parts['lid']), normal=parts['normal'])
            return dict(mesh=kernel.display_mesh(enc.box_enclosure(env, spec)))

        def show(value, error):
            if self.mode != 'enclosure' or getattr(self, '_enc_sig', None) != sig:
                return                                  # nieaktualny wynik (parametry zmieniły się w trakcie liczenia)
            if error or value is None:
                self.enc['exact_error_sig'] = sig
                self.enc_status.setText(str(error) if error else 'Nie udało się policzyć obudowy.')
                self.enc_apply.setEnabled(False)
                if split:
                    self.enc_step4.set_state('active', str(error or ''))
                return
            self.enc['exact_error_sig'] = None
            self._enc_exact_result = dict(value, sig=sig)
            if self.enc.get('drag') is None:
                self._enc_redisplay()
        self.run_preview('enclosure', compute, show)

    def _enc_redisplay(self):
        """Dokładny podgląd z ostatniego wyniku: przezroczystość i widok rozstrzelony bez ponownego liczenia geometrii."""
        if self.mode != 'enclosure':
            return
        result = getattr(self, '_enc_exact_result', None)
        spec = self.enc_spec() if self.enc.get('layout') is not None else None
        if result is None or spec is None or result['sig'] != self._enc_sig_of(spec):
            if spec is not None and self.enc.get('env') is not None:
                self._enc_quick_only(spec)
            return
        if 'mesh' in result:
            mesh = result['mesh']
        else:
            shift = np.asarray(result['normal'], float) * (self.enc_explode_dist.value() if self.enc_explode.isChecked() else 0.0)
            mesh = enc.merge_meshes([result['base'], enc.moved_mesh(result['lid'], shift) if shift.any() else result['lid']])
        self._enc_shown = ('exact', result['sig'])
        self.view.set_preview_mesh(mesh, color=(*PREVIEW_RGB, self._enc_alpha()), line_color=PREVIEW_LINE, width=2)

    def _enc_quick_only(self, spec):
        try:
            explode = self.enc_explode_dist.value() if self.enc_explode.isChecked() else 0.0
            mesh = enc.quick_mesh(self.enc['env'], spec, explode)
        except kernel.CadError:
            mesh = None
        self.view.set_preview_mesh(mesh, color=(*PREVIEW_RGB, self._enc_alpha() * .7), line_color=PREVIEW_LINE, width=1.6, dashed=True)

    # ------------------------------------------------------------------ przekrój podglądu
    def _enc_section(self):
        """Tymczasowy przekrój (płaszczyzna widoku - ten sam mechanizm co Widok przekroju), prostopadły do osi obudowy."""
        env = self.enc.get('env') if hasattr(self, 'enc') else None
        if self.mode != 'enclosure' or not self.enc_cut.isChecked() or env is None:
            if self.enc.get('section') is not None:
                self.enc['section'] = None
                self._enc_section_restore()
            return
        i = 'xyz'.index(self.enc_cut_axis.currentData())
        a = np.asarray(env.axes, float)[i]
        p = np.asarray(env.center, float) + a * self.enc_cut_pos.value()
        keep = -a                                  # zostaje strona ujemna - widać wnętrze od strony dodatniej osi
        plane = np.r_[keep, -keep @ p]
        self.enc['section'] = plane
        self.view.set_section_plane(plane)

    def _enc_section_restore(self):
        if self.section_button.isChecked() and self.section_origin is not None:
            self._section_update()                 # wraca przekrój ustawiony wcześniej narzędziem Widok przekroju
        else:
            self.view.set_section_plane(None)

    def enc_view_bodies(self, bodies):
        """refresh(): elementy wewnętrzne ukryte w widoku, gdy „Pokaż elementy w środku” jest wyłączone (dokument bez zmian)."""
        if getattr(self, 'mode', None) != 'enclosure' or not hasattr(self, 'enc_inner') or self.enc_inner.isChecked() or not hasattr(self, 'enc'):
            return bodies
        from dataclasses import replace
        hide = set(self.enc['ids'])
        return [replace(b, visible=False) if b.id in hide and b.visible else b for b in bodies]

    # ------------------------------------------------------------------ zapis
    def apply_enclosure(self):
        """Zastosuj: obudowa jako nowa bryła albo (podział) podstawa i pokrywa - dwie osobne bryły w grupie obudowy.
        Elementy źródłowe zostają bez zmian."""
        if self.busy or self.mode != 'enclosure':
            return
        if not self.enc['ids']:
            self.toast('Wybierz co najmniej jedną bryłę.')
            return
        if self.enc['env'] is None or self.enc.get('layout') is None or self.enc.get('split_error'):
            self.toast(self.enc.get('error') or 'Wskaż ścianę orientacji.')
            return
        spec = self.enc_spec()
        split = enc.split_of(spec)['enabled']
        names = {b.folder if (b.meta or {}).get('enclosure_part') else b.id for b in self.document.bodies
                 if b.kind == 'encl' or (b.meta or {}).get('enclosure')}
        count = 1 + len(names)
        name = f'Obudowa {count}'
        recipe = dict(type='enclosure', spec=spec.to_json(), out=uuid.uuid4().hex, name=name)
        if split:
            recipe.update(out_lid=uuid.uuid4().hex, folder=name)
        label = 'Obudowa z pokrywą' if split else 'Obudowa prostokątna'
        existing = list(self.document.bodies)

        def build():
            return enc.run(existing, recipe, check_sources=True)      # kolizja połączenia z elementami - błąd, nic nie powstaje

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = label
            self.document.pending_icon = 'enclosure'
            self.document.commit(bodies)

        def after():
            self.set_mode(None)
            made = [i for i in (recipe['out'], recipe.get('out_lid')) if i and self.document.get(i) is not None]
            if made:
                self.selected = made
                self.refresh()

        self._enc_timer.stop()
        self.view.set_preview_mesh(None)
        self.run_operation(label, build, apply, after=after)
