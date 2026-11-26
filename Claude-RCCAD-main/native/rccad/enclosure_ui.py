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
                               QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from . import dims
from . import enclosure as enc
from . import enclosure_shapes as shapes
from . import enclosure_mounts as mounts
from . import enclosure_posts as posts
from . import enclosure_closure as closure
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
        self._build_enc_templates(lay)                # etap 15: biblioteka szablonów i sposób montażu
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
        self.enc_step3 = ui.StepRow(3, 'x_enclosure', 'Obudowa', plain=True)
        lay.addWidget(self.enc_step3)
        self.enc_mode = QComboBox()
        for mode in enc.MODES:
            self.enc_mode.addItem(enc.MODE_LABELS[mode], mode)
        self.enc_mode.setCurrentIndex(self.enc_mode.findData('closed'))
        self.enc_mode.currentIndexChanged.connect(lambda *_: self._enc_params_changed())
        lay.addWidget(self.enc_mode)
        self._build_enc_shape(lay)
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
        self._build_enc_mounts(lay)
        self.enc_status = _label('Klikaj bryły (także z importu STEP) - kliknięcie dodaje albo usuwa z listy.', 'status')
        lay.addWidget(self.enc_status)
        self.enc_apply, _ = self._buttons(self.enc_panel.footer, 'Zastosuj', 'Anuluj', self.apply_enclosure, lambda: self.set_mode(None))
        return self.enc_panel

    def _build_enc_shape(self, lay):
        """Etap 5: kształt obudowy, jego parametry, orientacja i dopasowanie do elementów."""
        lay.addWidget(_label('Kształt obudowy', 'label'))
        self.enc_shape = QComboBox()
        for kind in shapes.SHAPES:
            self.enc_shape.addItem(shapes.SHAPE_LABELS[kind], kind)
        self.enc_shape.currentIndexChanged.connect(lambda *_: self._enc_shape_changed())
        lay.addWidget(self.enc_shape)
        self.enc_orient = QComboBox()
        self.enc_orient.setToolTip('Orientacja kształtu względem osi obudowy')
        self.enc_orient.currentIndexChanged.connect(lambda *_: self._enc_params_changed())
        lay.addWidget(self.enc_orient)
        self.enc_auto = QCheckBox('Dopasuj automatycznie do elementów')
        self.enc_auto.setChecked(True)
        self.enc_auto.setToolTip('Średnice / wysokości wyznaczane tak, by wszystkie elementy z odstępami mieściły się we wnętrzu '
                                 '(sprawdzane na rzeczywistej geometrii). Wyłączone - wpisane wymiary (zewnętrzne) są sprawdzane.')
        self.enc_auto.toggled.connect(lambda *_: self._enc_params_changed())
        lay.addWidget(self.enc_auto)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        self.enc_shape_rows = {}
        rows = (('radius', 'Promień narożników', _spin(shapes.SHAPE_DEFAULTS['radius'], .1, enc.MAX_VALUE, 2, .5, ' mm')),
                ('chamfer', 'Fazowanie', _spin(shapes.SHAPE_DEFAULTS['chamfer'], .1, enc.MAX_VALUE, 2, .5, ' mm')),
                ('sides', 'Liczba boków', QSpinBox()),
                ('diameter', 'Średnica', _spin(0, 0, enc.MAX_VALUE, 2, 1, ' mm')),
                ('dx', 'Średnica X', _spin(0, 0, enc.MAX_VALUE, 2, 1, ' mm')),
                ('dy', 'Średnica Y', _spin(0, 0, enc.MAX_VALUE, 2, 1, ' mm')),
                ('angle', 'Kąt pochylenia', _spin(shapes.SHAPE_DEFAULTS['angle'], -shapes.MAX_ANGLE + .1, shapes.MAX_ANGLE - .1, 1, 1, ' °')),
                ('front', 'Wysokość przednia', _spin(0, 0, enc.MAX_VALUE, 2, 1, ' mm')),
                ('back', 'Wysokość tylna', _spin(0, 0, enc.MAX_VALUE, 2, 1, ' mm')),
                ('degree', 'Stopień dopasowania (promień)', _spin(shapes.SHAPE_DEFAULTS['degree'], 0, enc.MAX_VALUE, 2, .5, ' mm')),
                ('min_radius', 'Min. promień narożników', _spin(shapes.SHAPE_DEFAULTS['min_radius'], 0, enc.MAX_VALUE, 2, .5, ' mm')),
                ('min_neck', 'Min. szerokość przewężeń', _spin(shapes.SHAPE_DEFAULTS['min_neck'], 0, enc.MAX_VALUE, 2, .5, ' mm')),
                ('accuracy', 'Dokładność obrysu', _spin(shapes.SHAPE_DEFAULTS['accuracy'], .01, 10, 3, .05, ' mm')),
                ('simplify', 'Tolerancja uproszczenia', _spin(shapes.SHAPE_DEFAULTS['simplify'], 0, 100, 3, .1, ' mm')),
                ('min_fragment', 'Pomijaj fragmenty mniejsze niż', _spin(shapes.SHAPE_DEFAULTS['min_fragment'], 0, 1e6, 2, .5, ' mm²')),
                ('layers', 'Warstwy przekroju (1 = stały)', QSpinBox()))
        for n, (key, title, box) in enumerate(rows):
            if key in ('sides', 'layers'):
                box.setRange(3, 64) if key == 'sides' else box.setRange(1, 12)
                box.setValue(shapes.SHAPE_DEFAULTS[key])
                box.setButtonSymbols(QSpinBox.NoButtons)
                box.setKeyboardTracking(False)
                if key == 'layers':
                    box.setToolTip('Przekrój zmienny: elementy dzielone na warstwy wzdłuż osi kształtu, każda warstwa ma własny obrys')
            box.valueChanged.connect(lambda *_: self._enc_params_changed())
            label = _label(title, 'label')
            grid.addWidget(label, n, 0)
            grid.addWidget(box, n, 1)
            self.enc_shape_rows[key] = (label, box)
        lay.addLayout(grid)
        from . import enclosure_contour as contour
        self.enc_cmode = QComboBox()
        for key in contour.CMODES:
            self.enc_cmode.addItem(contour.CMODE_LABELS[key], key)
        self.enc_cmode.setCurrentIndex(self.enc_cmode.findData('concave'))
        self.enc_cmode.currentIndexChanged.connect(lambda *_: self._enc_shape_changed())
        lay.addWidget(self.enc_cmode)
        self.enc_connect = QCheckBox('Łącz rozłączne obszary')
        self.enc_connect.setChecked(True)
        self.enc_connect.setToolTip('Obszary rzutów, które się nie stykają, łączone domknięciem o rosnącym promieniu')
        self.enc_connect.toggled.connect(lambda *_: self._enc_params_changed())
        lay.addWidget(self.enc_connect)
        self.enc_csketch = QPushButton('Wskaż szkic z konturem')
        self.enc_csketch.clicked.connect(lambda _=False: self._enc_pick_csketch())
        lay.addWidget(self.enc_csketch)
        self.enc_convex = QPushButton('Użyj obrysu wypukłego')
        self.enc_convex.setToolTip('Dokładne dopasowanie nie dało poprawnego konturu - obrys wypukły zawsze się udaje')
        self.enc_convex.clicked.connect(lambda _=False: self.enc_cmode.setCurrentIndex(self.enc_cmode.findData('convex')))
        lay.addWidget(self.enc_convex)
        self.enc_convex.setVisible(False)
        self._enc_shape_changed(update=False)

    SHAPE_FIELDS = {'box': (), 'rounded': ('radius',), 'chamfer': ('chamfer',), 'cylinder': ('diameter',), 'ellipse': ('dx', 'dy'),
                    'polygon': ('sides', 'diameter'), 'trapezoid': ('angle',), 'desk': ('angle', 'front', 'back'),
                    'contour': ('degree', 'min_radius', 'min_neck', 'accuracy', 'simplify', 'min_fragment', 'layers')}
    CONTOUR_FIELDS = {'convex': ('accuracy', 'simplify', 'layers'), 'concave': ('degree', 'min_neck', 'accuracy', 'simplify', 'min_fragment', 'layers'),
                      'exact': ('min_neck', 'accuracy', 'simplify', 'min_fragment', 'layers'),
                      'smooth': ('degree', 'min_radius', 'min_neck', 'accuracy', 'simplify', 'min_fragment', 'layers'),
                      'sketch': ('accuracy', 'simplify')}

    def _enc_pick_csketch(self):
        self.enc['picking_csketch'] = True
        self.enc_status.setText('Kliknij zamknięty szkic - jego kontur wyznaczy przekrój obudowy.')

    def _enc_csketch_click(self, x, y):
        sid = self.view.pick_profile(x, y)
        sk = self.document.get(sid) if sid else None
        if sk is None or sk.kind != 'sketch':
            self.toast('Kliknij zamknięty szkic.')
            return
        self.enc['picking_csketch'] = False
        self.enc['csketch'] = sk.id
        self.enc_csketch.setText(f'Szkic: {sk.name} (wskaż inny)')
        self._enc_params_changed()
    AUTO_FIELDS = ('diameter', 'dx', 'dy', 'front', 'back')

    def _enc_shape_changed(self, update=True):
        kind = self.enc_shape.currentData()
        self.enc_orient.blockSignals(True)
        self.enc_orient.clear()
        labels = shapes.TRAP_ORIENT_LABELS if kind == 'trapezoid' else shapes.ORIENT_LABELS
        for o in shapes.ORIENTS.get(kind, ()):
            self.enc_orient.addItem(labels[o], o)
        self.enc_orient.blockSignals(False)
        self.enc_orient.setVisible(kind in shapes.ORIENTS)
        self.enc_auto.setVisible(kind in ('cylinder', 'ellipse', 'polygon', 'desk'))
        fields = self.SHAPE_FIELDS.get(kind, ())
        contour_on = kind == 'contour'
        if contour_on:
            fields = self.CONTOUR_FIELDS.get(self.enc_cmode.currentData(), ()) if hasattr(self, 'enc_cmode') else fields
        for w_ in ('enc_cmode', 'enc_connect'):
            if hasattr(self, w_):
                getattr(self, w_).setVisible(contour_on)
        if hasattr(self, 'enc_csketch'):
            self.enc_csketch.setVisible(contour_on and self.enc_cmode.currentData() == 'sketch')
        for key, (label, box) in self.enc_shape_rows.items():
            label.setVisible(key in fields)
            box.setVisible(key in fields)
        self._enc_auto_widgets()
        if update:
            self._enc_params_changed()          # walidacja geometrii po każdej zmianie kształtu

    def _enc_auto_widgets(self):
        kind = self.enc_shape.currentData()
        auto = self.enc_auto.isChecked() or kind not in ('cylinder', 'ellipse', 'polygon', 'desk')
        for key in self.AUTO_FIELDS:
            self.enc_shape_rows[key][1].setEnabled(not auto)
        self.enc_shape_rows['angle'][1].setEnabled(kind != 'desk' or self.enc_auto.isChecked())   # pulpit ręcznie: kąt z wysokości

    def _enc_shape_info(self, info):
        """Dopasowane wymiary kształtu w polach (przy dopasowaniu automatycznym - tylko do odczytu)."""
        auto = self.enc_auto.isChecked()
        for key, value in (info or {}).items():
            box = self.enc_shape_rows.get(key, (None, None))[1]
            if box is None or (key != 'angle' and not auto) or (key == 'angle' and auto):
                continue
            if abs(box.value() - float(value)) > 5e-3:
                self._enc_set(box, round(float(value), 2))

    # ------------------------------------------------------------------ etap 6: punkty montażowe
    MOUNT_COLORS = {'approved': ((.1, .7, .3, .3), (.05, .6, .2, 1)), 'pending': ((1, .55, .1, .3), (.95, .45, .02, 1)),
                    'rejected': ((.6, .6, .6, .2), (.55, .55, .55, 1)), 'current': ((.2, .5, 1, .3), (.1, .35, .95, 1))}

    def _build_enc_mounts(self, lay):
        self.enc_step5 = ui.StepRow(5, 'x_enclosure', 'Punkty montażowe', plain=True)
        lay.addWidget(self.enc_step5)
        self.enc_detect = QPushButton('Wykryj otwory montażowe')
        self.enc_detect.setToolTip('Analiza powierzchni cylindrycznych elementów: otwory zwykłe, ślepe, pogłębione i stopniowane')
        self.enc_detect.clicked.connect(lambda _=False: self.enc_detect_mounts())
        lay.addWidget(self.enc_detect)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        grid.addWidget(_label('Średnica od', 'label'), 0, 0)
        self.enc_dmin = _spin(mounts.DEFAULT_FILTER['dmin'], 0, enc.MAX_VALUE, 2, .5, ' mm')
        grid.addWidget(self.enc_dmin, 0, 1)
        grid.addWidget(_label('do', 'label'), 0, 2)
        self.enc_dmax = _spin(mounts.DEFAULT_FILTER['dmax'], 0, enc.MAX_VALUE, 2, .5, ' mm')
        grid.addWidget(self.enc_dmax, 0, 3)
        self.enc_maxis = QComboBox()
        for key, text in (('all', 'Każdy kierunek osi'), ('x', 'Oś X obudowy'), ('y', 'Oś Y obudowy'), ('z', 'Oś Z obudowy')):
            self.enc_maxis.addItem(text, key)
        grid.addWidget(self.enc_maxis, 1, 0, 1, 4)
        self.enc_mkinds = {}
        for n, kind in enumerate(('plain', 'blind', 'counterbore', 'stepped')):
            box = QCheckBox(mounts.KIND_LABELS[kind])
            box.setChecked(True)
            box.toggled.connect(lambda *_: self._enc_mounts_show())
            grid.addWidget(box, 2 + n // 2, (n % 2) * 2, 1, 2)
            self.enc_mkinds[kind] = box
        for w_ in (self.enc_dmin, self.enc_dmax):
            w_.valueChanged.connect(lambda *_: self._enc_mounts_show())
        self.enc_maxis.currentIndexChanged.connect(lambda *_: self._enc_mounts_show())
        lay.addLayout(grid)
        self.enc_mount_list = QListWidget()
        self.enc_mount_list.setObjectName('enclist')
        self.enc_mount_list.setFixedHeight(120)
        self.enc_mount_list.setStyleSheet(self.enc_list.styleSheet())
        self.enc_mount_list.currentRowChanged.connect(lambda *_: (self._enc_mount_markers(), self._enc_post_load()))
        self.enc_mount_list.itemChanged.connect(lambda item: self._enc_mount_checked(item))
        lay.addWidget(self.enc_mount_list)
        row = QGridLayout()
        row.setHorizontalSpacing(6)
        row.setVerticalSpacing(5)
        buttons = (('Zatwierdź', lambda: self.enc_mount_set('approved')), ('Odrzuć', lambda: self.enc_mount_set('rejected')),
                   ('Zmień kierunek', self.enc_mount_flip), ('Usuń', self.enc_mount_delete),
                   ('Wskaż walec', lambda: self._enc_pick_mount('face')), ('Dodaj punkt', lambda: self._enc_pick_mount('point')))
        tips = {'Wskaż walec': 'Kliknij powierzchnię cylindryczną elementu - otwór z jej współosiowych ścian',
                'Dodaj punkt': 'Kliknij ścianę elementu - punkt montażowy z kierunkiem normalnej ściany',
                'Usuń': 'Usuwa punkt dodany ręcznie (wykryte otwory można odrzucić)'}
        self.enc_mount_buttons = {}
        for n, (text, fn) in enumerate(buttons):
            b = QPushButton(text)
            b.setToolTip(tips.get(text, ''))
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b, n // 2, n % 2)
            self.enc_mount_buttons[text] = b
        lay.addLayout(row)
        self.enc_mount_info = _label('Punkty montażowe: brak', 'small')
        lay.addWidget(self.enc_mount_info)
        self._build_enc_posts(lay)

    # ------------------------------------------------------------------ etap 7: mocowania
    POST_FIELDS = {'cylinder': ('diameter', 'height', 'hole_depth', 'gap'), 'rect': ('width', 'height', 'hole_depth', 'gap'),
                   'cone': ('diameter', 'top_diameter', 'height', 'hole_depth', 'gap'), 'ribbed': ('diameter', 'height', 'hole_depth', 'rib', 'ribs', 'gap'),
                   'snap': ('diameter', 'height', 'gap'), 'guide': ('length', 'groove', 'height', 'hole_depth', 'rib', 'gap'),
                   'support': ('diameter', 'height')}

    def _build_enc_posts(self, lay):
        self.enc_step6 = ui.StepRow(6, 'x_enclosure', 'Mocowania', plain=True)
        lay.addWidget(self.enc_step6)
        self.enc_posts_on = QCheckBox('Generuj mocowania w zatwierdzonych punktach')
        self.enc_posts_on.setChecked(True)
        self.enc_posts_on.toggled.connect(lambda *_: self._enc_posts_changed())
        lay.addWidget(self.enc_posts_on)
        self.enc_post_single = QCheckBox('Zmieniaj tylko wybrany punkt')
        self.enc_post_single.setToolTip('Wyłączone - zmiany dotyczą wszystkich mocowań (bez własnych ustawień); włączone - tylko punktu wybranego na liście')
        self.enc_post_single.toggled.connect(lambda *_: self._enc_post_load())
        lay.addWidget(self.enc_post_single)
        self.enc_post_type = QComboBox()
        for key in posts.POST_TYPES:
            self.enc_post_type.addItem(posts.POST_LABELS[key], key)
        self.enc_post_fasten = QComboBox()
        for key in posts.FASTENINGS:
            self.enc_post_fasten.addItem(posts.FASTEN_LABELS[key], key)
        self.enc_post_screw = QComboBox()
        for key in posts.SCREWS:
            self.enc_post_screw.addItem(key, key)
        for box in (self.enc_post_type, self.enc_post_fasten, self.enc_post_screw):
            box.currentIndexChanged.connect(lambda *_: self._enc_post_edited())
            lay.addWidget(box)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        self.enc_post_rows = {}
        rows = (('diameter', 'Średnica', 0.5), ('top_diameter', 'Średnica górna', 0.5), ('width', 'Szerokość', 0.5),
                ('height', 'Wysokość (0 = auto)', 0.0), ('hole_depth', 'Głębokość otworu (0 = auto)', 0.0), ('rib', 'Grubość żeber', 0.2),
                ('ribs', 'Liczba żeber', 2), ('gap', 'Luz montażowy', 0.0), ('groove', 'Rowek (grubość elementu)', 0.2), ('length', 'Długość prowadnicy', 1.0))
        for n, (key, title, low) in enumerate(rows):
            if key == 'ribs':
                box = QSpinBox()
                box.setRange(2, 8)
                box.setButtonSymbols(QSpinBox.NoButtons)
                box.setKeyboardTracking(False)
            else:
                box = _spin(0, low, enc.MAX_VALUE, 2, .5, ' mm')
            box.setValue(posts.DEFAULTS[key])
            box.valueChanged.connect(lambda *_: self._enc_post_edited())
            label = _label(title, 'label')
            grid.addWidget(label, n, 0)
            grid.addWidget(box, n, 1)
            self.enc_post_rows[key] = (label, box)
        lay.addLayout(grid)
        self.enc_post_thread = QCheckBox('Gwint kosmetyczny w otworze pod gwint')
        self.enc_post_thread.setToolTip('Opis gwintu przy bryle (jak Edycja → Gwint) - bez geometrii zwojów')
        self.enc_post_thread.toggled.connect(lambda *_: self._enc_post_edited())
        lay.addWidget(self.enc_post_thread)
        self.enc_post_reset = QPushButton('Przywróć wspólne ustawienia punktu')
        self.enc_post_reset.clicked.connect(lambda _=False: self._enc_post_reset())
        lay.addWidget(self.enc_post_reset)
        self.enc_post_info = _label('', 'small')
        lay.addWidget(self.enc_post_info)
        self.enc_posts = dict(posts.DEFAULTS)
        self._enc_post_load()
        self._build_enc_closure(lay)
        self._build_enc_tech(lay)
        self._build_enc_check(lay)

    def _enc_post_widgets(self, p):
        typ = p['type']
        fields = self.POST_FIELDS.get(typ, ())
        for key, (label, box) in self.enc_post_rows.items():
            label.setVisible(key in fields)
            box.setVisible(key in fields)
        holes = typ in ('cylinder', 'rect', 'cone', 'ribbed')
        self.enc_post_fasten.setVisible(holes)
        self.enc_post_screw.setVisible(holes or typ == 'snap')
        self.enc_post_thread.setVisible(holes and p['fastening'] == 'tapped')

    def _enc_post_target(self):
        """Edytowane ustawienia: wspólne albo nadpisania wybranego punktu."""
        if self.enc_post_single.isChecked():
            h = self._enc_mount(self._enc_current_mount_id())
            if h is not None:
                return h
        return None

    def _enc_post_load(self):
        """Pola mocowania z ustawień wspólnych albo wybranego punktu (wspólne + jego nadpisania)."""
        if not hasattr(self, 'enc_post_rows'):
            return
        h = self._enc_post_target()
        p = posts.params(self.enc_posts, h)
        widgets = [self.enc_post_type, self.enc_post_fasten, self.enc_post_screw, self.enc_post_thread, *[b for _l, b in self.enc_post_rows.values()]]
        for w_ in widgets:
            w_.blockSignals(True)
        self.enc_post_type.setCurrentIndex(max(0, self.enc_post_type.findData(p['type'])))
        self.enc_post_fasten.setCurrentIndex(max(0, self.enc_post_fasten.findData(p['fastening'])))
        self.enc_post_screw.setCurrentIndex(max(0, self.enc_post_screw.findData(p['screw'])))
        self.enc_post_thread.setChecked(bool(p.get('thread')))
        for key, (_l, box) in self.enc_post_rows.items():
            box.setValue(int(p[key]) if key == 'ribs' else float(p[key]))
        for w_ in widgets:
            w_.blockSignals(False)
        self.enc_post_reset.setEnabled(h is not None and bool(h.get('post')))
        self._enc_post_widgets(p)

    def _enc_post_values(self):
        out = dict(type=self.enc_post_type.currentData(), fastening=self.enc_post_fasten.currentData(), screw=self.enc_post_screw.currentData(),
                   thread=self.enc_post_thread.isChecked())
        for key, (_l, box) in self.enc_post_rows.items():
            out[key] = int(box.value()) if key == 'ribs' else float(box.value())
        return out

    def _enc_post_edited(self):
        values = self._enc_post_values()
        h = self._enc_post_target()
        if h is not None:                              # indywidualnie: tylko różnice względem wspólnych
            base = dict(posts.DEFAULTS, **self.enc_posts)
            h['post'] = {k: v for k, v in values.items() if base.get(k) != v}
            self.enc_post_reset.setEnabled(bool(h['post']))
        else:
            self.enc_posts.update(values)
        self._enc_post_widgets(posts.params(self.enc_posts, h))
        self._enc_posts_changed()

    def _enc_post_reset(self):
        h = self._enc_post_target()
        if h is not None:
            h['post'] = {}
        self._enc_post_load()
        self._enc_posts_changed()

    def _enc_posts_changed(self):
        on = self.enc_posts_on.isChecked()
        for w_ in (self.enc_post_single, self.enc_post_type, self.enc_post_fasten, self.enc_post_screw, self.enc_post_thread, self.enc_post_reset,
                   *[b for _l, b in self.enc_post_rows.values()]):
            w_.setEnabled(on if w_ is not self.enc_post_reset else (on and w_.isEnabled()))
        n = sum(1 for h in self.enc.get('mounts') or [] if h['status'] == 'approved')
        self.enc_step6.set_state('done' if (on and n) else 'pending', f'{n} mocowań' if (on and n) else ('wyłączone' if not on else 'brak punktów'))
        self._enc_live()

    # ------------------------------------------------------------------ etap 9: systemy zamykania
    CLOSURE_FIELDS = {
        'screw': [('screw', 'Rozmiar śruby', {k: k for k in posts.SCREWS}), ('fastening', 'Mocowanie w podstawie', {'pilot': 'wkręt (otwór wstępny)', 'insert': 'insert termiczny', 'nut': 'nakrętka'}),
                  ('boss', 'Średnica słupka', None), ('head', 'Średnica łba', None), ('head_depth', 'Głębokość pogłębienia', None), ('gap', 'Luz', None)],
        'snap': [('width', 'Szerokość ramienia', None), ('thickness', 'Grubość ramienia', None), ('length', 'Długość ramienia', None),
                 ('hook', 'Głębokość zaczepu', None), ('hook_h', 'Wysokość zaczepu', None), ('ramp', 'Kąt najazdu (°)', None), ('gap', 'Luz', None),
                 ('per_side', 'Zatrzaski na długim boku', None)],
        'slide': [('axis', 'Kierunek wsuwania', 'axes'), ('open', 'Strona otwarta', {'+': 'po stronie +', '-': 'po stronie −'}), ('depth', 'Głębokość rowka', None),
                  ('lip', 'Listwa nad pokrywą', None), ('gap', 'Luz', None)],
        'dovetail': [('axis', 'Kierunek wsuwania', 'axes'), ('open', 'Strona otwarta', {'+': 'po stronie +', '-': 'po stronie −'}), ('depth', 'Głębokość rowka', None),
                     ('lip', 'Listwa nad pokrywą', None), ('angle', 'Kąt jaskółczego ogona (°)', None), ('gap', 'Luz', None)],
        'hinge': [('side', 'Ścianka zawiasów', 'sides'), ('count', 'Liczba zawiasów', None), ('knuckles', 'Liczba kostek', None), ('diameter', 'Średnica kostek', None),
                  ('length', 'Długość zawiasu', None), ('pin', 'Średnica sworznia', None), ('gap', 'Luz', None), ('angle', 'Sprawdzany kąt otwarcia (°)', None)],
        'magnet': [('diameter', 'Średnica magnesu', None), ('height', 'Wysokość magnesu', None), ('gap', 'Luz', None), ('boss', 'Średnica słupka', None)],
        'press': [('pin', 'Średnica kołka', None), ('pin_h', 'Wysokość kołka', None), ('fit', 'Pasowanie (ujemne - wcisk)', None), ('boss', 'Średnica słupka', None)],
        'gasket': [('width', 'Szerokość rowka', None), ('depth', 'Głębokość rowka', None)]}

    def _build_enc_closure(self, lay):
        self.enc_step7 = ui.StepRow(7, 'x_enclosure', 'System zamykania', plain=True)
        lay.addWidget(self.enc_step7)
        lay.addWidget(_label('Wymaga podziału na podstawę i pokrywę (krok 4). Można łączyć kilka systemów.', 'small'))
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        self.enc_cl_on = {}
        for n, kind in enumerate(closure.SYSTEMS):
            box = QCheckBox(closure.LABELS[kind])
            box.toggled.connect(lambda on, k=kind: self._enc_closure_toggled(k, on))
            grid.addWidget(box, n // 2, n % 2)
            self.enc_cl_on[kind] = box
        lay.addLayout(grid)
        self.enc_cl_edit = QComboBox()
        self.enc_cl_edit.setToolTip('System, którego parametry i rozmieszczenie edytujesz')
        self.enc_cl_edit.currentIndexChanged.connect(lambda *_: self._enc_closure_form())
        lay.addWidget(self.enc_cl_edit)
        self.enc_cl_form = QWidget()
        self.enc_cl_grid = QGridLayout(self.enc_cl_form)
        self.enc_cl_grid.setContentsMargins(0, 0, 0, 0)
        self.enc_cl_grid.setHorizontalSpacing(6)
        self.enc_cl_grid.setVerticalSpacing(5)
        lay.addWidget(self.enc_cl_form)
        self.enc_cl_items = QListWidget()
        self.enc_cl_items.setObjectName('enclist')
        self.enc_cl_items.setFixedHeight(92)
        self.enc_cl_items.setStyleSheet(self.enc_list.styleSheet())
        self.enc_cl_items.itemChanged.connect(lambda item: self._enc_closure_item_changed(item))
        self.enc_cl_items.currentRowChanged.connect(lambda *_: self._enc_closure_item_load())
        lay.addWidget(self.enc_cl_items)
        row = QGridLayout()
        row.setHorizontalSpacing(6)
        self.enc_cl_pos = {}
        for n, (key, title) in enumerate((('pos', 'Położenie na boku (%)'), ('da', 'Przesunięcie 1 (mm)'), ('db', 'Przesunięcie 2 (mm)'))):
            box = _spin(0, -1e4, 1e4, 2, 1)
            box.valueChanged.connect(lambda *_: self._enc_closure_item_edit())
            label = _label(title, 'label')
            row.addWidget(label, n, 0)
            row.addWidget(box, n, 1)
            self.enc_cl_pos[key] = (label, box)
        reset = QPushButton('Rozmieść automatycznie')
        reset.setToolTip('Usuwa ręczne korekty położenia elementów tego systemu')
        reset.clicked.connect(lambda _=False: self._enc_closure_reset())
        row.addWidget(reset, 3, 0, 1, 2)
        lay.addLayout(row)
        self.enc_cl_report = _label('', 'small')
        lay.addWidget(self.enc_cl_report)
        self.enc_closure = {k: dict(type=k, enabled=False, params={}, items={}) for k in closure.SYSTEMS}
        self._enc_closure_form()

    def _enc_closure_toggled(self, kind, on):
        self.enc_closure[kind]['enabled'] = bool(on)
        if on and not self.enc_split_on.isChecked():
            self.enc_split_on.setChecked(True)          # system zamykania łączy podstawę z pokrywą - włącza podział
        if on and kind in ('slide', 'dovetail'):
            self._enc_slide_split()
        current = self.enc_cl_edit.currentData()
        self.enc_cl_edit.blockSignals(True)
        self.enc_cl_edit.clear()
        for k, sy in self.enc_closure.items():
            if sy['enabled']:
                self.enc_cl_edit.addItem(closure.LABELS[k], k)
        idx = self.enc_cl_edit.findData(kind if on else current)
        self.enc_cl_edit.setCurrentIndex(max(0, idx))
        self.enc_cl_edit.blockSignals(False)
        self._enc_closure_form()
        self._enc_live()

    def _enc_slide_split(self):
        """Pokrywa wsuwana jest płytką: podział na wewnętrznej powierzchni górnej ścianki, połączenie płaskie."""
        layout, env = self.enc.get('layout'), self.enc.get('env')
        if layout is None or env is None:
            return
        mode = self.enc_split_mode.currentData() if self.enc_split_mode.currentData() in ('x', 'y', 'z') else 'z'
        i = 'xyz'.index(mode)
        for w_, val in ((self.enc_split_mode, mode), (self.enc_split_unit, 'mm'), (self.enc_joint, 'flat')):
            w_.blockSignals(True)
            w_.setCurrentIndex(w_.findData(val))
            w_.blockSignals(False)
        self._enc_set(self.enc_split_pos, round(float(layout['inner'][1][i] - layout['outer'][0][i]), 4))

    def _enc_axis_names(self):
        mode = self.enc_split_mode.currentData()
        i = 'xyz'.index(mode) if mode in ('x', 'y', 'z') else 2
        a, b = [n for n in 'XYZ' if n != 'XYZ'[i]]
        return a, b

    def _enc_closure_form(self):
        """Pola parametrów wybranego systemu (budowane od nowa przy zmianie systemu)."""
        while self.enc_cl_grid.count():
            item = self.enc_cl_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        kind = self.enc_cl_edit.currentData()
        self.enc_cl_widgets = {}
        if kind is None:
            self.enc_cl_form.setVisible(False)
            self._enc_closure_items()
            return
        self.enc_cl_form.setVisible(True)
        p = closure.params(self.enc_closure[kind])
        a, b = self._enc_axis_names()
        for n, (key, title, opts) in enumerate(self.CLOSURE_FIELDS[kind]):
            if opts == 'axes':
                opts = {'a': f'wzdłuż osi {a}', 'b': f'wzdłuż osi {b}'}
            elif opts == 'sides':
                opts = {'a-': f'{a}−', 'a+': f'{a}+', 'b-': f'{b}−', 'b+': f'{b}+'}
            if opts:
                box = QComboBox()
                for val, text in opts.items():
                    box.addItem(text, val)
                box.setCurrentIndex(max(0, box.findData(p[key])))
                box.currentIndexChanged.connect(lambda *_, k=kind: self._enc_closure_edited(k))
            elif key in ('per_side', 'count', 'knuckles'):
                box = QSpinBox()
                box.setRange(1 if key != 'knuckles' else 2, 9)
                box.setButtonSymbols(QSpinBox.NoButtons)
                box.setKeyboardTracking(False)
                box.setValue(int(p[key]))
                box.valueChanged.connect(lambda *_, k=kind: self._enc_closure_edited(k))
            else:
                box = _spin(float(p[key]), -1e4, 1e4, 2, .1 if abs(float(p[key])) < 5 else 1)
                box.valueChanged.connect(lambda *_, k=kind: self._enc_closure_edited(k))
            self.enc_cl_grid.addWidget(_label(title, 'label'), n, 0)
            self.enc_cl_grid.addWidget(box, n, 1)
            self.enc_cl_widgets[key] = box
        self._enc_closure_items()

    def _enc_closure_edited(self, kind):
        vals = {}
        for key, box in self.enc_cl_widgets.items():
            vals[key] = box.currentData() if isinstance(box, QComboBox) else (int(box.value()) if isinstance(box, QSpinBox) else float(box.value()))
        self.enc_closure[kind]['params'] = vals
        self._enc_closure_items()
        self._enc_live()

    def _enc_closure_frame(self):
        layout, env, plane = self.enc.get('layout'), self.enc.get('env'), self.enc.get('plane')
        if layout is None or plane is None:
            return None
        try:
            return closure.Frame(env, self.enc_spec(), layout, plane)
        except kernel.CadError:
            return None

    def _enc_closure_items(self):
        kind = self.enc_cl_edit.currentData()
        self.enc_cl_items.blockSignals(True)
        self.enc_cl_items.clear()
        fr = self._enc_closure_frame() if kind else None
        items = []
        if fr is not None:
            sy = self.enc_closure[kind]
            items = closure.items_of(fr, dict(sy, items=list(sy['items'].values())))
            a, b = self._enc_axis_names()
            for it in items:
                if 'side' in it:
                    k, sign = it['side']
                    name = (a if k == fr.a else b) + ('+' if sign > 0 else '−')
                    text = f'ściana {name} · {it["pos"] * 100:.0f}%'
                else:
                    text = f'narożnik {it["key"][1:].replace("-1", "−").replace("+1", "+")} · przesunięcie {it.get("da", 0):g} / {it.get("db", 0):g} mm'
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, it['key'])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if it['enabled'] else Qt.Unchecked)
                self.enc_cl_items.addItem(item)
        self.enc_cl_items.blockSignals(False)
        self.enc_cl_items.setVisible(bool(items))
        self._enc_cl_cache = {it['key']: it for it in items}
        self._enc_closure_item_load()

    def _enc_closure_item_load(self):
        item = self.enc_cl_items.currentItem()
        it = self._enc_cl_cache.get(item.data(Qt.UserRole)) if item is not None else None
        side = it is not None and 'side' in it
        for key, (label, box) in self.enc_cl_pos.items():
            vis = it is not None and ((key == 'pos') == side)
            label.setVisible(vis)
            box.setVisible(vis)
            if vis:
                box.blockSignals(True)
                box.setValue(float(it['pos']) * 100 if key == 'pos' else float(it.get(key, 0.0)))
                box.blockSignals(False)

    def _enc_closure_item_edit(self):
        kind = self.enc_cl_edit.currentData()
        item = self.enc_cl_items.currentItem()
        if kind is None or item is None:
            return
        key = item.data(Qt.UserRole)
        it = self._enc_cl_cache.get(key)
        over = dict(self.enc_closure[kind]['items'].get(key, {'key': key}))
        if 'side' in it:
            over['pos'] = max(0.0, min(1.0, self.enc_cl_pos['pos'][1].value() / 100))
        else:
            over.update(da=self.enc_cl_pos['da'][1].value(), db=self.enc_cl_pos['db'][1].value())
        self.enc_closure[kind]['items'][key] = over
        row = self.enc_cl_items.currentRow()
        self._enc_closure_items()
        self.enc_cl_items.setCurrentRow(row)
        self._enc_live()

    def _enc_closure_item_changed(self, item):
        kind = self.enc_cl_edit.currentData()
        if kind is None:
            return
        key = item.data(Qt.UserRole)
        over = dict(self.enc_closure[kind]['items'].get(key, {'key': key}))
        over['enabled'] = item.checkState() == Qt.Checked
        self.enc_closure[kind]['items'][key] = over
        self._enc_live()

    def _enc_closure_on(self):
        return any(sy['enabled'] for sy in getattr(self, 'enc_closure', {}).values())

    def _enc_closure_report(self, report):
        colors = {'ok': '#1e8449', 'warning': '#b9770e', 'error': '#c0392b', 'info': '#17314a'}
        words = {'ok': 'Poprawne', 'warning': 'Ostrzeżenie', 'error': 'Błąd', 'info': ''}
        lines = [f'<span style="color:{colors[lvl]}">{(words[lvl] + ": ") if words[lvl] else "• "}{text}</span>' for lvl, text in report]
        self.enc_cl_report.setText('<br>'.join(lines))
        on = self._enc_closure_on()
        self.enc_step7.set_state('done' if on else 'pending', ', '.join(closure.LABELS[k].lower() for k, sy in self.enc_closure.items() if sy['enabled']) or 'brak')

    def _enc_closure_reset(self):
        kind = self.enc_cl_edit.currentData()
        if kind is not None:
            self.enc_closure[kind]['items'] = {}
            self._enc_closure_items()
            self._enc_live()

    # ------------------------------------------------------------------ etap 14: technologia produkcji
    TECH_FIELDS = {
        'print': [('min_wall', 'Minimalna grubość ścianki', None), ('nozzle', 'Średnica dyszy', None), ('fit', 'Luz montażowy', None),
                  ('overhang', 'Graniczny kąt nawisu (°)', None), ('orient', 'Orientacja druku', {'auto': 'automatycznie (podstawa dnem, pokrywa górą)',
                   'z+': 'Z w górę', 'z-': 'Z w dół', 'x+': 'X w górę', 'x-': 'X w dół', 'y+': 'Y w górę', 'y-': 'Y w dół'}),
                  ('bed_x', 'Przestrzeń robocza X', None), ('bed_y', 'Przestrzeń robocza Y', None), ('bed_z', 'Przestrzeń robocza Z', None),
                  ('split', 'Dziel za duże części (kołki)', 'bool'), ('pin', 'Średnica kołka', None), ('pin_len', 'Długość kołka', None)],
        'sheet': [('t', 'Grubość blachy', None), ('r', 'Promień gięcia', None), ('k', 'Współczynnik K', None), ('gap', 'Szczelina narożna', None),
                  ('relief', 'Podcięcie technologiczne', {'none': 'brak', 'square': 'prostokątne', 'round': 'okrągłe'}), ('relief_size', 'Wielkość podcięcia', None)],
        'cnc': [('tool', 'Średnica narzędzia', None), ('min_radius', 'Min. promień wewnętrzny', None), ('depth', 'Głębokość kieszeni podstawy (0 = połowa)', None),
                ('dogbone', 'Podcięcia dogbone (ostre narożniki)', 'bool'), ('floor', 'Min. grubość dna', None)],
        'laser': [('t', 'Grubość materiału', None), ('kerf', 'Szczelina cięcia (kerf)', None), ('fit', 'Luz montażowy', None), ('finger', 'Długość noska', None),
                  ('holes', 'Otwory montażowe z punktów', 'bool'), ('hole', 'Średnica otworów', None), ('flat', 'Płyty rozłożone na płaszczyźnie', 'bool')]}

    def _build_enc_tech(self, lay):
        from . import enclosure_tech as tech
        self.enc_step9 = ui.StepRow(9, 'x_enclosure', 'Technologia produkcji', plain=True)
        lay.addWidget(self.enc_step9)
        self.enc_tech = QComboBox()
        for key in tech.TECHS:
            self.enc_tech.addItem(tech.TECH_LABELS[key], key)
        self.enc_tech.currentIndexChanged.connect(lambda *_: self._enc_tech_form())
        lay.addWidget(self.enc_tech)
        self.enc_tech_form = QWidget()
        self.enc_tech_grid = QGridLayout(self.enc_tech_form)
        self.enc_tech_grid.setContentsMargins(0, 0, 0, 0)
        self.enc_tech_grid.setHorizontalSpacing(6)
        self.enc_tech_grid.setVerticalSpacing(5)
        lay.addWidget(self.enc_tech_form)
        lay.addWidget(_label('Analiza technologiczna (klik - podświetlenie):', 'small'))
        self.enc_tech_list, self.enc_tech_sum = self._check_widgets(lay, 'tech')
        self.enc_tech_params = {k: dict(v) for k, v in tech.DEFAULTS.items()}
        self._enc_tech_form(update=False)

    def _enc_tech_on(self):
        return hasattr(self, 'enc_tech') and self.enc_tech.currentData() not in (None, 'none')

    def _enc_tech_form(self, update=True):
        while self.enc_tech_grid.count():
            item = self.enc_tech_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        kind = self.enc_tech.currentData()
        self.enc_tech_widgets = {}
        for n, (key, title, opts) in enumerate(self.TECH_FIELDS.get(kind, [])):
            val = self.enc_tech_params[kind][key]
            if opts == 'bool':
                box = QCheckBox(title)
                box.setChecked(bool(val))
                box.toggled.connect(lambda *_, k=kind: self._enc_tech_edited(k))
                self.enc_tech_grid.addWidget(box, n, 0, 1, 2)
            else:
                if opts:
                    box = QComboBox()
                    for v, text in opts.items():
                        box.addItem(text, v)
                    box.setCurrentIndex(max(0, box.findData(val)))
                    box.currentIndexChanged.connect(lambda *_, k=kind: self._enc_tech_edited(k))
                else:
                    box = _spin(float(val), 0, 1e4, 3 if key in ('k', 'kerf', 'nozzle') else 2, .05 if float(val) < 2 else .5)
                    box.valueChanged.connect(lambda *_, k=kind: self._enc_tech_edited(k))
                self.enc_tech_grid.addWidget(_label(title, 'label'), n, 0)
                self.enc_tech_grid.addWidget(box, n, 1)
            self.enc_tech_widgets[key] = box
        self.enc_tech_form.setVisible(kind not in (None, 'none'))
        from . import enclosure_tech as tech
        self.enc_step9.set_state('done' if kind not in (None, 'none') else 'pending', tech.TECH_LABELS.get(kind, '').split('· ')[-1].lower())
        if update:
            self._enc_live()

    def _enc_tech_edited(self, kind):
        for key, box in self.enc_tech_widgets.items():
            if isinstance(box, QCheckBox):
                self.enc_tech_params[kind][key] = box.isChecked()
            elif isinstance(box, QComboBox):
                self.enc_tech_params[kind][key] = box.currentData()
            else:
                self.enc_tech_params[kind][key] = float(box.value())
        self._enc_live()

    def _enc_filter(self):
        return dict(dmin=self.enc_dmin.value(), dmax=self.enc_dmax.value(), axis=self.enc_maxis.currentData(),
                    kinds=tuple(k for k, b in self.enc_mkinds.items() if b.isChecked()))

    def enc_detect_mounts(self):
        """Wykrywanie w tle; zatwierdzone / odrzucone wcześniej otwory zachowują decyzję, ręczne punkty zostają."""
        if self.enc.get('env') is None:
            self.toast('Najpierw wybierz elementy obudowy.')
            return
        bodies, ids, env = list(self.document.bodies), list(self.enc['ids']), self.enc['env']
        self.enc_mount_info.setText('Wykrywanie otworów…')

        def compute():
            return mounts.detect(bodies, ids, env)

        def show(found, error):
            if self.mode != 'enclosure':
                return
            if error or found is None:
                self.enc_mount_info.setText(f'Wykrywanie nie powiodło się: {error}')
                return
            old = self.enc.get('mounts') or []
            key = lambda h: (h.get('source'), tuple(round(c, 3) for c in h['center']), round(h['diameter'], 3))
            decided = {key(h): h for h in old if not h.get('manual')}
            for h in found:
                prev = decided.get(key(h)) or decided.get((h.get('source'), tuple(round(c, 3) for c in self._other_end(h)), round(h['diameter'], 3)))
                if prev is not None:
                    h.update(status=prev['status'], axis=prev['axis'], center=prev['center'], side=prev.get('side'),
                             accessible=prev.get('accessible', True), id=prev['id'])
            self.enc['mounts'] = [h for h in old if h.get('manual')] + found
            self._enc_mounts_show()
        self.run_preview('encmounts', compute, show)

    @staticmethod
    def _other_end(h):
        ends = h.get('ends') or [h['center'], h['center']]
        c = np.asarray(h['center'], float)
        a, b = (np.asarray(e, float) for e in ends)
        return b if np.linalg.norm(c - a) < np.linalg.norm(c - b) else a

    def _enc_visible_mounts(self):
        flt = self._enc_filter()
        return [h for h in (self.enc.get('mounts') or []) if mounts.passes(h, flt)]

    def _enc_mounts_show(self, keep=None):
        if not hasattr(self, 'enc_mount_list'):
            return
        shown = self._enc_visible_mounts()
        current = keep or self._enc_current_mount_id()
        self.enc_mount_list.blockSignals(True)
        self.enc_mount_list.clear()
        mark = {'approved': '✓', 'rejected': '✗', 'pending': '•'}
        for h in shown:
            item = QListWidgetItem(f'{mark.get(h["status"], "•")} {mounts.describe(h)}')
            item.setData(Qt.UserRole, h['id'])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if h['status'] == 'approved' else Qt.Unchecked)
            item.setToolTip(f'Głębokość {h["depth"]:.2f} mm · oś {tuple(round(c, 3) for c in h["axis"])} · środek '
                            f'{tuple(round(c, 2) for c in h["center"])}' + ('' if h.get('accessible', True) else ' · oś za wejściem trafia w inny element'))
            self.enc_mount_list.addItem(item)
            if h['id'] == current:
                self.enc_mount_list.setCurrentItem(item)
        self.enc_mount_list.blockSignals(False)
        allm = self.enc.get('mounts') or []
        ok = sum(1 for h in allm if h['status'] == 'approved')
        self.enc_mount_info.setText(f'Zatwierdzone: {ok} · do decyzji: {sum(1 for h in allm if h["status"] == "pending")} · '
                                    f'odrzucone: {sum(1 for h in allm if h["status"] == "rejected")} · ukryte filtrem: {len(allm) - len(shown)}')
        self.enc_step5.set_state('done' if ok else ('active' if allm else 'pending'), f'{ok} zatwierdzone' if allm else 'opcjonalnie')
        self._enc_mount_markers()
        if hasattr(self, 'enc_step6'):
            on = self.enc_posts_on.isChecked()
            self.enc_step6.set_state('done' if (on and ok) else 'pending', f'{ok} mocowań' if (on and ok) else ('wyłączone' if not on else 'brak punktów'))
            self._enc_post_load()
        self._enc_live()                         # zatwierdzone punkty z mocowaniami zmieniają geometrię

    def _enc_current_mount_id(self):
        item = self.enc_mount_list.currentItem() if hasattr(self, 'enc_mount_list') else None
        return item.data(Qt.UserRole) if item is not None else None

    def _enc_mount(self, mid):
        return next((h for h in self.enc.get('mounts') or [] if h['id'] == mid), None)

    def _enc_mount_markers(self):
        """Tymczasowe znaczniki 3D: zielony - zatwierdzony, pomarańczowy - do decyzji, szary - odrzucony, niebieski - bieżący."""
        if self.mode != 'enclosure':
            return
        shown = self._enc_visible_mounts()
        cur = self._enc_current_mount_id()
        size = max(1.0, .03 * float(np.max(self.enc['env'].size))) if self.enc.get('env') is not None else 1.0
        meshes = []
        for status in ('rejected', 'pending', 'approved', 'current'):
            group = [h for h in shown if (h['id'] == cur) == (status == 'current') and (status == 'current' or h['status'] == status)]
            mesh = mounts.marker_mesh(group, size) if group else None
            if mesh is not None:
                meshes.append((mesh, *self.MOUNT_COLORS[status]))
        self.view.set_selection_meshes(meshes)

    def _enc_mount_checked(self, item):
        h = self._enc_mount(item.data(Qt.UserRole))
        if h is not None:
            h['status'] = 'approved' if item.checkState() == Qt.Checked else ('rejected' if h['status'] == 'approved' else h['status'])
            self._enc_mounts_show(keep=h['id'])

    def enc_mount_set(self, status, mid=None):
        h = self._enc_mount(mid or self._enc_current_mount_id())
        if h is None:
            self.toast('Wybierz otwór z listy albo kliknij jego znacznik.')
            return
        h['status'] = status
        self._enc_mounts_show(keep=h['id'])

    def enc_mount_flip(self, mid=None):
        h = self._enc_mount(mid or self._enc_current_mount_id())
        if h is None:
            self.toast('Wybierz otwór z listy albo kliknij jego znacznik.')
            return
        h.update(mounts.flipped(h, self.enc.get('env'), self.document.bodies))
        self._enc_mounts_show(keep=h['id'])

    def enc_mount_delete(self, mid=None):
        h = self._enc_mount(mid or self._enc_current_mount_id())
        if h is None:
            return
        if not h.get('manual'):
            self.toast('Wykrytego otworu nie usuwa się - odrzuć go.')
            return
        self.enc['mounts'] = [x for x in self.enc['mounts'] if x['id'] != h['id']]
        self._enc_mounts_show()

    def _enc_pick_mount(self, what):
        if not self.enc['ids']:
            self.toast('Najpierw wybierz elementy obudowy.')
            return
        self.enc['picking_mount'] = what
        self.enc.update(picking_face=False, picking_split=False)
        self.hint('Kliknij powierzchnię cylindryczną elementu.' if what == 'face' else
                  'Kliknij ścianę elementu w miejscu punktu montażowego (kierunek - normalna ściany).')
        self.enc_status.setText('Kliknij powierzchnię cylindryczną elementu.' if what == 'face' else 'Kliknij ścianę elementu - punkt montażowy.')

    def _enc_mount_click(self, x, y):
        """Klik w trybie wskazywania otworu / punktu; poza nim - klik w znacznik wybiera otwór na liście."""
        what = self.enc.get('picking_mount')
        if what:
            hit = self.view.pick_face(x, y)
            body = self.document.get(hit[0]) if hit else None
            if body is None or body.id not in self.enc['ids'] or body.kind != 'solid':
                self.toast('Kliknij element obudowy (bryłę z listy).')
                return True
            try:
                face, normal = self.view.face_at(body, hit, curved=True)
                if what == 'face':
                    h = mounts.from_face(body, face, self.document.bodies, self.enc.get('env'))
                else:
                    h = mounts.manual_point(body, hit[2], normal, self.document.bodies, self.enc.get('env'))
            except kernel.CadError as exc:
                self.toast(str(exc))
                return True
            except Exception as exc:
                self.toast(f'Nie udało się odczytać ściany: {exc}')
                return True
            self.enc['picking_mount'] = None
            self.enc.setdefault('mounts', [])
            self.enc['mounts'] = [*self.enc['mounts'], h]
            self._enc_mounts_show(keep=h['id'])
            self._enc_live(exact=False)
            return True
        shown = self._enc_visible_mounts()
        best = None
        for h in shown:
            p = self.view.project_one(np.asarray(h['center'], float))
            if p is None:
                continue
            d = float(np.hypot(p[0] - x, p[1] - y))
            if d < 14 and (best is None or d < best[0]):
                best = (d, h)
        if best is not None:
            self._enc_mounts_show(keep=best[1]['id'])
            return True
        return False

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
        if hasattr(self, 'enc_shape_rows'):
            self._enc_auto_widgets()
        self._enc_live()

    # ------------------------------------------------------------------ tryb
    def _enclosure_begin(self, previous=()):
        """set_mode('enclosure'): zaznaczone wcześniej bryły od razu na liście."""
        self.enc = dict(ids=[], face=None, picking_face=False, picking_split=False, env=None, error=None, split_face=None,
                        mounts=[], picking_mount=None, rules=[])
        self._enc_exact_result = None
        if hasattr(self, 'enc_tpl_info'):
            self.enc_tpl_info.setText('')
            self._enc_tpl_fill()
        self.enc_frame.blockSignals(True)
        self.enc_frame.setCurrentIndex(0)
        self.enc_frame.blockSignals(False)
        for box in (self.enc_cut, self.enc_explode):
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
        self.enc_panel.show()
        self.enc_set_ids([i for i in previous if self._enc_ok(self.document.get(i))])
        self._enc_mounts_show()
        self.hint('Utwórz obudowę: klikaj bryły, które mają być w obudowie (ponowne kliknięcie usuwa z listy).')
        self.view.setCursor(Qt.PointingHandCursor)

    def _enclosure_end(self):
        self.enc_items = []
        self._enc_replace = None
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
        if self.enc.get('mounts'):
            self.enc['mounts'] = [h for h in self.enc['mounts'] if h.get('source') in seen]   # punkty usuniętych elementów znikają
            self._enc_mounts_show()
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
        if self.enc.get('picking_mount'):
            mesh = body.mesh if (body is not None and body.id in self.enc['ids']) else None
        elif self.enc['picking_face'] or self.enc.get('picking_split'):
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
        if self.enc.get('picking_csketch'):
            self._enc_csketch_click(x, y)
            return
        if (self.enc.get('mounts') or self.enc.get('picking_mount')) and self._enc_mount_click(x, y):
            return                                   # punkty montażowe: wskazanie walca / punktu albo wybór znacznika
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
        if mode == 'axes':                                   # układ z optymalizacji: osie zachowane przy edycji
            spec.frame = enc.FrameSpec(mode=mode, face=dict(axes=(face or {}).get('axes') or [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]))
        else:
            spec.frame = enc.FrameSpec(mode=mode, face=dict(id=face['id'], point=face['point']) if (mode == 'face' and face) else None)
        spec.mode = self.enc_mode.currentData()
        spec.shape = self.enc_shape.currentData()
        if spec.shape != 'box':
            spec.shape_params = dict({k: (int(b.value()) if k in ('sides', 'layers') else float(b.value())) for k, (_l, b) in self.enc_shape_rows.items()},
                                     orient=self.enc_orient.currentData() or '', auto=self.enc_auto.isChecked())
            if spec.shape == 'contour':
                spec.shape_params.update(cmode=self.enc_cmode.currentData(), connect=self.enc_connect.isChecked(), sketch=self.enc.get('csketch'))
        spec.clearance = dict({k: float(b.value()) for k, b in self.enc_clear.items()}, linked=self.enc_clear_link.isChecked())
        spec.walls = dict({k: float(b.value()) for k, b in self.enc_wall.items()}, linked=self.enc_wall_link.isChecked())
        cut = self.enc.get('split_face')
        spec.split = dict(enabled=self.enc_split_on.isChecked(), mode=self.enc_split_mode.currentData(),
                          plane=self.enc_split_plane.currentData(), face=dict(id=cut['id'], point=cut['point']) if cut else None,
                          unit=self.enc_split_unit.currentData(), position=float(self.enc_split_pos.value()),
                          joint=self.enc_joint.currentData(), **{k: float(s.value()) for k, s in self.enc_joint_spins.items()})
        spec.mounts = [mounts.stored(h) for h in self.enc.get('mounts') or [] if h['status'] == 'approved']
        if hasattr(self, 'enc_posts_on') and self.enc_posts_on.isChecked() and spec.mounts:
            spec.posts = dict(self.enc_posts, enabled=True)
        if hasattr(self, 'enc_tech') and self._enc_tech_on():
            kind = self.enc_tech.currentData()
            spec.process = dict(tech=kind, **{kind: dict(self.enc_tech_params[kind])})
        if hasattr(self, 'enc_mounting') and self.enc_mounting.currentData():
            spec.process = dict(spec.process or {}, mounting=self.enc_mounting.currentData())
        if hasattr(self, 'enc_closure') and spec.split.get('enabled'):
            systems = [dict(type=k, enabled=True, params=dict(sy['params']), items=list(sy['items'].values()))
                       for k, sy in self.enc_closure.items() if sy['enabled']]
            if systems:
                spec.closure = dict(systems=systems)
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
                                 {'global': 'globalny', 'local': 'lokalny (OBB)', 'axes': 'obrócony (optymalizacja)'}.get(mode) or (f'ściana · {face["name"]}' if face else 'wskaż ścianę'))
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
        points = None
        if env is not None:
            try:
                points = shapes.source_points(env, self.enc_spec(), self.document.bodies)
            except Exception:
                points = None
        self.enc.update(env=env, env_error=error, points=points)
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
                layout = enc.layout(env, spec, points=self.enc.get('points'), bodies=self.document.bodies, verify=False)   # bez Boolean (dokładnie: w tle)
            except kernel.CadError as exc:
                error = str(exc)
            if layout is not None and layout.get('info'):
                self._enc_shape_info(layout['info'])
        sp = enc.split_of(spec)
        split_error = None
        if layout is not None and sp['enabled']:
            try:
                plane = enc.split_check(env, spec, layout, self.document.bodies)
            except kernel.CadError as exc:
                split_error = str(exc)
        self.enc.update(error=error or split_error, layout=layout, plane=plane, split_error=split_error)
        if hasattr(self, 'enc_convex'):
            self.enc_convex.setVisible(spec.shape == 'contour' and layout is None and env is not None and self.enc_cmode.currentData() != 'convex')
        ok = layout is not None and split_error is None and not self.enc.get('exact_error_sig') == self._enc_sig_of(spec)
        self.enc_apply.setEnabled(ok)       # niepoprawne wartości: Zastosuj zablokowane
        self.enc_step3.set_state('done' if layout is not None else ('active' if env is not None else 'pending'),
                                 (self.enc_shape.currentText().lower() + ' · ' + self.enc_mode.currentText().split(' (')[0].lower())
                                 if layout is not None else (error or '') if env is not None else '')
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
            items = [] if kind == 'outer' else enc.outer_dimension_items(env, spec, lay=layout)
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
        if hasattr(self, 'enc_cl_items') and self._enc_closure_on():
            row = self.enc_cl_items.currentRow()
            self._enc_closure_items()               # rozmieszczenie zależy od płaszczyzny podziału i wymiarów
            if 0 <= row < self.enc_cl_items.count():
                self.enc_cl_items.setCurrentRow(row)
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
        data = spec.to_json()
        if not data.get('posts'):
            data.pop('mounts', None)             # punkty bez mocowań nie zmieniają geometrii obudowy
        return repr(data)

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
            mesh = enc.quick_mesh(env, spec, explode, self.enc.get('layout'))
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
            from .enclosure_check_ui import results_with_meshes
            report, extra = [], {}
            parts, _threads, info = enc.build_parts(env, spec, bodies, check_sources=True, report=report, extra=extra)   # podział, zamknięcie, mocowania, technologia
            report = [(r[0], r[1], r[2] if len(r) > 2 else None) for r in report]
            tech_report = results_with_meshes([(lvl, text, sh, None) for lvl, text, sh in report])
            if set(parts) == {'base', 'lid'} and split and not extra:
                plane = enc.split_plane(env, spec, enc.layout(env, spec, bodies=bodies), bodies)
                return dict(base=kernel.display_mesh(parts['base']), lid=kernel.display_mesh(parts['lid']), normal=plane[1], posts=info,
                            report=[r[:2] for r in report], tech=tech_report)
            if set(parts) == {'body'} and not extra:
                return dict(mesh=kernel.display_mesh(parts['body']), posts=info, report=[r[:2] for r in report], tech=tech_report)
            shapes = [*parts.values(), *(extra.get('flats') or {}).values()]            # technologia: wszystkie części i rozkroje
            return dict(mesh=enc.merge_meshes([kernel.display_mesh(x) for x in shapes]), posts=info, report=[r[:2] for r in report], tech=tech_report)

        def show(value, error):
            if self.mode != 'enclosure' or getattr(self, '_enc_sig', None) != sig:
                return                                  # nieaktualny wynik (parametry zmieniły się w trakcie liczenia)
            if error or value is None:
                if hasattr(self, 'enc_cl_report') and self.enc.get('split_error') is None and self._enc_closure_on():
                    self.enc_cl_report.setText(f'<span style="color:#c0392b">Błąd: {error}</span>')
                self.enc['exact_error_sig'] = sig
                self.enc_status.setText(str(error) if error else 'Nie udało się policzyć obudowy.')
                self.enc_apply.setEnabled(False)
                if split:
                    self.enc_step4.set_state('active', str(error or ''))
                return
            self.enc['exact_error_sig'] = None
            self._enc_exact_result = dict(value, sig=sig)
            if hasattr(self, 'enc_cl_report'):
                self._enc_closure_report([r for r in value.get('report') or [] if not self._enc_tech_on()])
            if hasattr(self, 'enc_tech_list'):
                self._check_show('tech', value.get('tech') or [], self.enc_tech_list, self.enc_tech_sum)
            if hasattr(self, 'enc_post_info'):
                info = value.get('posts') or []
                self.enc_post_info.setText('' if not info else 'Wysokości: ' + ', '.join(
                    f'{i["height"]:.2f}' + ('' if abs(i['height'] - i['auto_height']) < 1e-6 else f' (auto {i["auto_height"]:.2f})') for i in info) + ' mm')
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
            mesh = enc.quick_mesh(self.enc['env'], spec, explode, self.enc.get('layout'))
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
    # ------------------------------------------------------------------ etap 13: edycja zapisanej obudowy
    def _enc_load_spec(self, spec):
        """Okno z parametrami zapisanej obudowy (edycja kroku albo dwuklik w obudowę)."""
        from . import enclosure_shapes as shp
        set_combo = lambda box, val: (box.blockSignals(True), box.setCurrentIndex(max(0, box.findData(val))), box.blockSignals(False))
        set_spin = lambda box, val: self._enc_set(box, val)
        set_check = lambda box, on: (box.blockSignals(True), box.setChecked(bool(on)), box.blockSignals(False))
        set_combo(self.enc_frame, spec.frame.mode)
        self.enc['face'] = dict(spec.frame.face, name='ściana') if spec.frame.face else None
        set_combo(self.enc_mode, spec.mode)
        set_combo(self.enc_shape, spec.shape or 'box')
        self._enc_shape_changed(update=False)
        p = shp.params_of(spec) if (spec.shape or 'box') != 'box' else {}
        if p:
            set_combo(self.enc_orient, p.get('orient'))
            set_check(self.enc_auto, p.get('auto', True))
            for key, (_l, box) in self.enc_shape_rows.items():
                if key in p and p[key] is not None:
                    set_spin(box, int(p[key]) if key in ('sides', 'layers') else float(p[key]))
            if spec.shape == 'contour':
                set_combo(self.enc_cmode, p.get('cmode'))
                set_check(self.enc_connect, p.get('connect', True))
                self.enc['csketch'] = p.get('sketch')
        c, w = enc.clearance_of(spec), enc.walls_of(spec)
        set_check(self.enc_clear_link, (spec.clearance or {}).get('linked', False))
        set_check(self.enc_wall_link, (spec.walls or {}).get('linked', False))
        for k, box in self.enc_clear.items():
            set_spin(box, c[k])
        for k, box in self.enc_wall.items():
            set_spin(box, w[k])
        sp = enc.split_of(spec)
        set_check(self.enc_split_on, sp['enabled'])
        set_combo(self.enc_split_mode, sp['mode'])
        set_combo(self.enc_split_plane, sp['plane'])
        set_combo(self.enc_split_unit, sp['unit'])
        set_spin(self.enc_split_pos, float(sp['position']))
        set_combo(self.enc_joint, sp['joint'])
        for k, box in self.enc_joint_spins.items():
            set_spin(box, float(sp[k]))
        self.enc['split_face'] = dict(sp['face'], name='ściana') if sp.get('face') else None
        self.enc['mounts'] = [dict(m, status='approved', post=m.get('post') or {}) for m in spec.mounts or []]
        set_check(self.enc_posts_on, bool(spec.posts))
        self.enc_posts = dict(posts.DEFAULTS, **{k: v for k, v in (spec.posts or {}).items() if k != 'enabled'})
        for k, sy in self.enc_closure.items():
            sy.update(enabled=False, params={}, items={})
        for sy in (spec.closure or {}).get('systems', []):
            self.enc_closure[sy['type']].update(enabled=True, params=dict(sy.get('params') or {}), items={it['key']: it for it in sy.get('items') or []})
            set_check(self.enc_cl_on[sy['type']], True)
        self.enc_cl_edit.clear()
        for k, sy in self.enc_closure.items():
            if sy['enabled']:
                self.enc_cl_edit.addItem(closure.LABELS[k], k)
        self._enc_closure_form()
        self._enc_post_load()
        from . import enclosure_tech as tech
        kind = tech.tech_of(spec)
        if kind != 'none':
            self.enc_tech_params[kind].update(tech.params(spec))
        set_combo(self.enc_tech, kind)
        self._enc_tech_form(update=False)
        if hasattr(self, 'enc_mounting'):
            set_combo(self.enc_mounting, (spec.process or {}).get('mounting') or '')
        self.enc_set_ids([s.id for s in spec.sources])
        self._enc_mounts_show()

    def _step_fill_enclosure(self, recipe):
        self._enc_load_spec(enc.EnclosureSpec.from_json(recipe['spec']))
        self.toast('Edycja obudowy: zmień parametry i kliknij Zastosuj - dalsze kroki (otwory, wentylacja) przeliczą się same.', 6000)

    def edit_enclosure(self, body_id):
        """Dwuklik w obudowę: okno z zachowanymi parametrami. Z krokiem tworzącym - edycja tego kroku (dalsze kroki zostają
        i przeliczają się), bez niego - przebudowa tych samych brył."""
        from . import enclosure_param as ep
        body = self.document.get(body_id)
        if body is None or not (body.meta or {}).get('enclosure') or self.busy:
            return False
        if (body.meta or {}).get('enclosure_mode') == 'frozen':
            self.toast('Parametry tej obudowy są zamrożone - zmień tryb w Kontroli obudowy, aby ją edytować.', 5000)
            return True
        ids = {b.id for b in ep.group(self.document.bodies, body)}
        for index, (_b, info) in enumerate(self.document.states()):
            op = info.get('op') or {}
            if op.get('type') == 'enclosure' and ids & {op.get('out'), op.get('out_lid')}:
                self.history_edit(index)
                return True
        base = next((b for b in ep.group(self.document.bodies, body) if (b.meta or {}).get('enclosure_part') in (None, 'base')), body)
        lid = next((b for b in ep.group(self.document.bodies, body) if (b.meta or {}).get('enclosure_part') == 'lid'), None)
        self.set_mode('enclosure')
        self._enc_replace = dict(out=base.id, out_lid=lid.id if lid else None, name=base.folder or base.name, folder=base.folder)
        self._enc_load_spec(enc.EnclosureSpec.from_json(body.meta['enclosure']))
        self.toast(f'Edycja {base.folder or base.name}: Zastosuj przebuduje te same bryły.', 5000)
        return True

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
        editing = (getattr(self, '_step_edit', None) or {}).get('recipe') or {}
        editing = editing if editing.get('type') == 'enclosure' else (getattr(self, '_enc_replace', None) or {})
        if editing:                                  # edycja istniejącej obudowy: te same bryły (dalsze kroki - otwory - je znajdą)
            name = editing.get('name') or 'Obudowa'
            recipe = dict(type='enclosure', spec=spec.to_json(), out=editing['out'], name=name)
            if split:
                recipe.update(out_lid=editing.get('out_lid') or uuid.uuid4().hex, folder=editing.get('folder') or name)
            elif editing.get('out_lid'):
                recipe['drop'] = [editing['out_lid']]
        else:
            names = {b.folder if (b.meta or {}).get('enclosure_part') else b.id for b in self.document.bodies
                     if b.kind == 'encl' or (b.meta or {}).get('enclosure')}
            count = 1 + len(names)
            name = f'Obudowa {count}'
            recipe = dict(type='enclosure', spec=spec.to_json(), out=uuid.uuid4().hex, name=name)
            if split:
                recipe.update(out_lid=uuid.uuid4().hex, folder=name)
        if self.__dict__.get('_enc_replace'):
            spec_meta = {k: v for k, v in (self.document.get(editing['out']).meta or {}).items() if k == 'enclosure_mode'} if self.document.get(editing['out']) else {}
            recipe['keep'] = spec_meta
        label = 'Obudowa z pokrywą' if split else ('Obudowa prostokątna' if spec.shape == 'box' else 'Obudowa (kształt)')
        existing = list(self.document.bodies)

        def build():
            return enc.run(existing, recipe, check_sources=True)      # kolizja połączenia z elementami - błąd, nic nie powstaje

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = label
            self.document.pending_icon = 'enclosure'
            self.document.commit(bodies)

        rules = [] if editing else list(self.enc.get('rules') or [])

        def after():
            self.set_mode(None)
            made = [i for i in (recipe['out'], recipe.get('out_lid')) if i and self.document.get(i) is not None]
            if made:
                self.selected = made
                self.refresh()
                if rules:                             # etap 15: reguły szablonu (wentylacja) - osobne kroki po obudowie
                    self._enc_apply_rules(made, rules)

        self._enc_timer.stop()
        self.view.set_preview_mesh(None)
        self.run_operation(label, build, apply, after=after)
