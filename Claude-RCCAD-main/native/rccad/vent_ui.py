"""Wentylacja - okno narzędzia (zakładka Wzory → Wentylacja): PreviewManager, edycja pojedynczych otworów,
manipulatory, biblioteka z miniaturami, szablony. Geometria: vent_feature (krok historii 'vent')."""
from __future__ import annotations

import copy
import uuid

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog, QLineEdit, QListView,
                               QListWidget, QListWidgetItem, QProgressBar, QPushButton, QToolButton, QVBoxLayout, QWidget)

from . import kernel
from . import shell_ui as ui
from . import vent_cut as vc
from . import vent_feature as vf
from . import vent_layout as vl
from . import vent_library as lib
from . import vent_shapes as vs
from . import vent_surface as su
from .enclosure_ui import _label, _spin

_STATE = {'cancel': False, 'progress': 0.0}
COLORS = {'ok': ((.25, .75, .4, .30), (.05, .55, .2, 1)), 'adjust': ((.95, .8, .2, .35), (.75, .55, .0, 1)),
          'bad': ((.9, .25, .2, .35), (.75, .1, .1, 1)), 'skip': ((.6, .6, .62, .15), (.5, .5, .55, .8)), 'zone': ((.9, .2, .2, .12), (.85, .1, .1, 1))}
LEVELS = ('fast', 'spatial', 'exact')
LEVEL_LABELS = {'fast': 'Szybki podgląd (obrysy na powierzchni)', 'spatial': 'Podgląd przestrzenny (bryły narzędzi)', 'exact': 'Dokładny podgląd (wynik cięcia)'}
# (klucz, tytuł, wartość, min, max, miejsca, krok, jednostka)
SHAPE_FIELDS = (('w', 'Średnica / szerokość otworu', 4.0, .1, 1000, 2, .5, ' mm'), ('h', 'Wysokość / długość otworu', 4.0, .1, 1000, 2, .5, ' mm'),
                ('corner', 'Promień narożników', 0.0, 0.0, 100, 2, .25, ' mm'), ('sides', 'Liczba boków', 6, 3, 64, 0, 1, ''),
                ('arms', 'Liczba ramion gwiazdy', 5, 3, 64, 0, 1, ''), ('ratio', 'Proporcje / promień wewnętrzny', .45, .05, .95, 2, .05, ''),
                ('arm', 'Szerokość ramion krzyża', .3, .05, .95, 2, .05, ''), ('bend', 'Wygięcie fasolki', 60.0, 5, 170, 1, 5, ' °'),
                ('irregularity', 'Nieregularność', .4, 0, .9, 2, .05, ''))
LAYOUT_FIELDS = (('px', 'Rozstaw poziomy (0 = otwór + mostek)', 0.0, 0, 1000, 2, .5, ' mm'), ('py', 'Rozstaw pionowy (0 = jak poziomy)', 0.0, 0, 1000, 2, .5, ' mm'),
                 ('rows', 'Liczba rzędów (0 = auto)', 0, 0, 2000, 0, 1, ''), ('cols', 'Liczba kolumn (0 = auto)', 0, 0, 2000, 0, 1, ''),
                 ('count', 'Całkowita liczba otworów (tryb B)', 0, 0, 20000, 0, 1, ''), ('angle', 'Obrót całego wzoru', 0.0, -360, 360, 1, 5, ' °'),
                 ('hole_angle', 'Obrót otworów', 0.0, -360, 360, 1, 5, ' °'), ('ox', 'Przesunięcie X', 0.0, -1e4, 1e4, 2, .5, ' mm'),
                 ('oy', 'Przesunięcie Y', 0.0, -1e4, 1e4, 2, .5, ' mm'), ('scale', 'Skala wzoru', 1.0, .05, 20, 2, .05, ''),
                 ('shift_row', 'Przesunięcie kolejnych rzędów', 50.0, 0, 100, 1, 5, ' %'), ('shift_col', 'Przesunięcie kolejnych kolumn', 0.0, 0, 100, 1, 5, ' %'),
                 ('seed', 'Seed (losowość)', 1, 0, 999999, 0, 1, ''), ('alt_angle', 'Kąt naprzemienny', 90.0, -360, 360, 1, 5, ' °'),
                 ('spiral_arms', 'Ramiona spirali', 1, 1, 32, 0, 1, ''))
GEN_FIELDS = (('arms_n', 'Liczba ramion / promieni', 6, 1, 128, 0, 1, ''), ('turns', 'Liczba obrotów spirali', 3.0, .25, 50, 2, .25, ''),
              ('pitch', 'Skok spirali (0 = auto)', 0.0, 0, 500, 2, .5, ' mm'), ('amplitude', 'Amplituda fal', 3.0, 0, 200, 2, .25, ' mm'),
              ('frequency', 'Częstotliwość fal', .1, .001, 10, 3, .01, ' 1/mm'), ('phase', 'Przesunięcie fazowe', 0.0, -360, 360, 1, 5, ' °'),
              ('channel', 'Szerokość kanałów', 2.0, .2, 100, 2, .25, ' mm'), ('branch_density', 'Gęstość rozgałęzień', .5, 0, 1, 2, .05, ''),
              ('branch_angle', 'Kąt rozgałęzień', 30.0, 5, 90, 1, 5, ' °'), ('level', 'Poziom rekurencji', 3, 1, 6, 0, 1, ''),
              ('cell', 'Wielkość komórki', 8.0, .5, 500, 2, .5, ' mm'), ('opening', 'Stopień otwarcia', .35, 0, .6, 2, .05, ''),
              ('gyro_phase', 'Faza (Gyroid)', 0.0, -6.3, 6.3, 2, .1, ' rad'), ('relax', 'Iteracje relaksacji Lloyda', 2, 0, 50, 0, 1, ''),
              ('cell_min', 'Min. wielkość komórki (0 = bez)', 0.0, 0, 500, 2, .5, ' mm'), ('cell_max', 'Maks. wielkość komórki (0 = bez)', 0.0, 0, 500, 2, .5, ' mm'),
              ('round_r', 'Zaokrąglenie narożników komórek', .5, 0, 50, 2, .1, ' mm'), ('smoothing', 'Wygładzanie (iteracje)', 0, 0, 6, 0, 1, ''),
              ('irregular', 'Stopień nieregularności', .5, 0, 1, 2, .05, ''), ('fan', 'Rozmiar wentylatora', 40, 10, 400, 0, 1, ' mm'),
              ('fan_d', 'Średnica obszaru wentylacji (0 = auto)', 0.0, 0, 500, 2, .5, ' mm'), ('fan_hub', 'Średnica pełnego środka (0 = auto)', 0.0, 0, 500, 2, .5, ' mm'),
              ('fan_spacing', 'Rozstaw otworów montażowych (0 = z karty)', 0.0, 0, 500, 2, .5, ' mm'), ('fan_hole', 'Średnica otworu montażowego (0 = z karty)', 0.0, 0, 20, 2, .1, ' mm'))
EDGE_FIELDS = (('margin', 'Margines od krawędzi', 2.0, 0, 500, 2, .5, ' mm'), ('margin_holes', 'Margines od istniejących otworów', 2.0, 0, 500, 2, .5, ' mm'),
               ('bridge', 'Minimalna szerokość mostków', 1.2, 0, 100, 2, .1, ' mm'), ('min_area', 'Min. pole przyciętego otworu', 1.0, 0, 1e4, 2, .5, ' mm²'),
               ('min_width', 'Min. szerokość przyciętego otworu', .8, 0, 100, 2, .1, ' mm'), ('min_scale', 'Min. skala zmniejszanego otworu', .4, .05, 1, 2, .05, ''),
               ('target_open', 'Docelowa powierzchnia otwarta (tryb D)', 30.0, 1, 90, 1, 1, ' %'), ('size_min', 'Min. wielkość otworu (tryb D)', 1.0, .1, 500, 2, .5, ' mm'),
               ('size_max', 'Maks. wielkość otworu (tryb D)', 20.0, .1, 500, 2, .5, ' mm'), ('obstacle_gap', 'Odstęp od stref zabronionych', 2.0, 0, 500, 2, .5, ' mm'))
CUT_FIELDS = (('depth', 'Głębokość', 1.0, .01, 1e4, 2, .25, ' mm'), ('depth2', 'Głębokość w drugą stronę', 1.0, .01, 1e4, 2, .25, ' mm'),
              ('dir_angle', 'Kąt do powierzchni', 60.0, 5, 90, 1, 5, ' °'), ('tilt', 'Nachylenie otworów', 0.0, -80, 80, 1, 5, ' °'),
              ('size_in', 'Wymiar wejścia (× profil)', 1.0, .05, 10, 2, .05, ''), ('size_out', 'Wymiar wyjścia (× profil)', .6, .05, 10, 2, .05, ''),
              ('size_mid', 'Wymiar w połowie (× profil)', .7, .05, 10, 2, .05, ''), ('step_depth', 'Głębokość stopnia', 1.0, .01, 100, 2, .25, ' mm'),
              ('step_scale', 'Wymiar stopnia (× profil)', 1.6, 1.01, 10, 2, .05, ''), ('chamfer', 'Fazowanie / promień zaokrąglenia', .4, 0, 50, 2, .05, ' mm'),
              ('louver_angle', 'Kąt łopatek żaluzji', 35.0, 5, 85, 1, 5, ' °'), ('louver_h', 'Wysokość łopatek', 3.0, .2, 100, 2, .25, ' mm'),
              ('louver_t', 'Grubość łopatek', 1.0, .1, 20, 2, .1, ' mm'), ('obstacle_factor', 'Próg elementu za ścianką (× grubość)', 1.6, 1.05, 10, 2, .05, ''))
COMBOS_AREA = (('kind', vs.SHAPE_LABELS), ('layout', vl.LAYOUT_LABELS), ('fill', vl.FILL_LABELS), ('edge_mode', vl.EDGE_LABELS),
               ('obstacle_mode', {k: 'Przeszkody: ' + v for k, v in vl.EDGE_LABELS.items()}), ('mix_mode', {'sequence': 'Mieszanie: sekwencja', 'alternate': 'Mieszanie: naprzemiennie',
                                                                                                         'percent': 'Mieszanie: udział procentowy'}),
               ('mirror_axis', {'x': 'Oś lustra: pozioma', 'y': 'Oś lustra: pionowa'}), ('twist', {'ccw': 'Skręt w lewo', 'cw': 'Skręt w prawo'}),
               ('adjust', {'size': 'Tryb D: dobieraj wielkość', 'spacing': 'Tryb D: dobieraj rozstaw'}),
               ('vmode', {'regular': 'Voronoi: regularny', 'random': 'Voronoi: losowy', 'organic': 'Voronoi: organiczny', 'gradient': 'Voronoi: gradientowy'}),
               ('fan_style', {k: 'Kratka: ' + v for k, v in vl.FAN_STYLE_LABELS.items()}))
COMBOS_CUT = (('direction', vc.DIRECTION_LABELS), ('depth_mode', vc.DEPTH_LABELS), ('hole_type', vc.HOLE_TYPE_LABELS),
              ('louver_dir', {'up': 'Żaluzje otwarte w górę (+Y wzoru)', 'down': 'Żaluzje otwarte w dół'}),
              ('profile_mode', {'tangent': 'Profil w płaszczyźnie stycznej (kształt)', 'mapped': 'Profil odwzorowany na powierzchnię (odstępy)'}))
REGION_FIELDS = (('cx', 'Środek obszaru X', 0.0, -1e4, 1e4, 2, .5, ' mm'), ('cy', 'Środek obszaru Y', 0.0, -1e4, 1e4, 2, .5, ' mm'),
                 ('w', 'Szerokość obszaru', 40.0, .5, 1e4, 2, .5, ' mm'), ('h', 'Wysokość obszaru', 30.0, .5, 1e4, 2, .5, ' mm'),
                 ('d', 'Średnica obszaru', 40.0, .5, 1e4, 2, .5, ' mm'), ('d2', 'Średnica wewnętrzna', 20.0, 0, 1e4, 2, .5, ' mm'),
                 ('sides', 'Liczba boków obszaru', 6, 3, 64, 0, 1, ''), ('a0', 'Kąt początkowy', 0.0, -360, 360, 1, 5, ' °'),
                 ('a1', 'Kąt końcowy', 90.0, -360, 360, 1, 5, ' °'), ('angle', 'Obrót obszaru', 0.0, -360, 360, 1, 5, ' °'),
                 ('scale', 'Skala obszaru', 1.0, .05, 20, 2, .05, ''))
REGION_USE = {'face': (), 'rect': ('cx', 'cy', 'w', 'h', 'angle', 'scale'), 'square': ('cx', 'cy', 'w', 'angle', 'scale'), 'circle': ('cx', 'cy', 'd', 'scale'),
              'ellipse': ('cx', 'cy', 'w', 'h', 'angle', 'scale'), 'polygon': ('cx', 'cy', 'd', 'sides', 'angle', 'scale'),
              'ring': ('cx', 'cy', 'd', 'd2', 'scale'), 'sector': ('cx', 'cy', 'd', 'd2', 'a0', 'a1', 'angle', 'scale'),
              'sketch': (), 'edges': (), 'contours': (), 'between': (), 'lasso': ()}
GEN_USE = {'voronoi': ('cell', 'relax', 'cell_min', 'cell_max', 'round_r', 'smoothing', 'irregular', 'count', 'seed'), 'gyroid2d': ('cell', 'opening', 'gyro_phase', 'angle'),
           'gyroid3d': ('cell',), 'zigzag': ('channel', 'amplitude', 'frequency', 'phase', 'angle', 'py'), 'sine': ('channel', 'amplitude', 'frequency', 'phase', 'angle', 'py'),
           'spiral': ('channel', 'arms_n', 'turns', 'pitch', 'twist'), 'turbine': ('channel', 'arms_n', 'branch_angle', 'twist', 'fan_hub'),
           'arcs': ('channel', 'arms_n', 'py'), 'labyrinth': ('channel', 'cell', 'seed'), 'weave': ('channel', 'px', 'py'), 'herringbone': ('channel', 'px', 'py'),
           'branches': ('channel', 'arms_n', 'branch_density', 'branch_angle', 'irregular', 'seed', 'px'), 'bubbles': ('w', 'size_min', 'seed'),
           'fishscale': ('w', 'ratio', 'px', 'py'), 'fractal': ('level', 'scale', 'angle'), 'leaves': ('w', 'branch_angle', 'px', 'py'),
           'fan': ('fan', 'fan_style', 'fan_d', 'fan_hub', 'fan_spacing', 'fan_hole', 'arms_n', 'channel', 'cell', 'w', 'h'),
           'radial_slots': ('channel', 'arms_n')}
LAYOUT_USE = {'rect': ('px', 'py', 'rows', 'cols', 'count', 'angle', 'ox', 'oy', 'scale'), 'square': ('px', 'rows', 'cols', 'count', 'angle', 'ox', 'oy', 'scale'),
              'offset_h': ('px', 'py', 'rows', 'cols', 'count', 'angle', 'ox', 'oy', 'scale', 'shift_row'), 'offset_v': ('px', 'py', 'rows', 'cols', 'count', 'angle', 'ox', 'oy', 'scale', 'shift_col'),
              'triangular': ('px', 'rows', 'cols', 'count', 'angle', 'ox', 'oy', 'scale'), 'hexagonal': ('px', 'rows', 'cols', 'count', 'angle', 'ox', 'oy', 'scale'),
              'diagonal': ('px', 'py', 'angle', 'ox', 'oy', 'scale'), 'radial': ('py', 'arms_n', 'angle', 'ox', 'oy'), 'concentric': ('px', 'py', 'angle', 'ox', 'oy'),
              'spiral': ('px', 'spiral_arms', 'twist', 'angle', 'ox', 'oy'), 'random': ('px', 'seed'), 'gradient': ('px', 'seed'),
              'alternating': ('px', 'py', 'alt_angle', 'angle', 'ox', 'oy', 'scale'), 'mirror': ('px', 'py', 'mirror_axis', 'angle', 'ox', 'oy', 'scale'),
              'curve': ('px', 'py', 'rows'), 'sketch': (), 'adaptive': ('px', 'py')}


class _Section(QWidget):
    """Rozwijana sekcja panelu: nagłówek (strzałka + tytuł) i treść."""

    def __init__(self, title, opened=False):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.button = QToolButton()
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setChecked(opened)
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.setArrowType(Qt.DownArrow if opened else Qt.RightArrow)
        self.button.setStyleSheet('QToolButton{border:none;font-weight:700;color:#27415a;text-align:left;}')
        self.body = QWidget()
        self.inner = QVBoxLayout(self.body)
        self.inner.setContentsMargins(4, 0, 0, 4)
        self.inner.setSpacing(6)
        self.body.setVisible(opened)
        self.button.toggled.connect(self._toggle)
        lay.addWidget(self.button)
        lay.addWidget(self.body)

    def _toggle(self, on):
        self.body.setVisible(on)
        self.button.setArrowType(Qt.DownArrow if on else Qt.RightArrow)


class VentTools:
    # ------------------------------------------------------------------ panel
    def _build_vent_panel(self):
        self.vn = self._vent_fresh()
        self._vn_timer = QTimer(self)
        self._vn_timer.setSingleShot(True)
        self._vn_timer.setInterval(450)
        self._vn_timer.timeout.connect(lambda: self._vn_preview())
        self._vn_poll = QTimer(self)
        self._vn_poll.setInterval(250)
        self._vn_poll.timeout.connect(lambda: self.vn_bar.setValue(int(100 * _STATE['progress'])))
        self.vn_panel, lay = self._panel(340, 'Wentylacja', 'x_vent', 'Powierzchnie → obszar → wzór → otwory', plain=True, scroll=True)
        self.vn_step1 = ui.StepRow(1, 'x_vent', 'Powierzchnie', plain=True)
        lay.addWidget(self.vn_step1)
        self.vn_w = {}                                                   # klucz → (etykieta, pole, grupa)
        self.vn_c = {}

        def section(title, opened=False):
            s = _Section(title, opened)
            lay.addWidget(s)
            return s.inner

        def combo(box_lay, key, items, group):
            box = QComboBox()
            for k_, title in items.items():
                box.addItem(title, k_)
            box.currentIndexChanged.connect(lambda *_: self._vn_changed(key, group))
            box_lay.addWidget(box)
            self.vn_c[key] = (box, group)
            return box

        def fields(box_lay, rows, group):
            grid = QGridLayout()
            grid.setHorizontalSpacing(6)
            for n, (key, title, val, lo, hi, dec, step, suf) in enumerate(rows):
                box = _spin(float(val), float(lo), float(hi), dec, step, suf)
                box.valueChanged.connect(lambda *_, k_=key, g_=group: self._vn_changed(k_, g_))
                lab = _label(title, 'label')
                grid.addWidget(lab, n, 0)
                grid.addWidget(box, n, 1)
                self.vn_w[(group, key)] = (lab, box)
            box_lay.addLayout(grid)
        # 1. powierzchnie
        s = section('1. Powierzchnie', True)
        self.vn_faces = _label('Kliknij ścianę bryły (Shift - kolejne ściany).', 'value')
        self.vn_faces.setWordWrap(True)
        s.addWidget(self.vn_faces)
        row = QHBoxLayout()
        b = QPushButton('Wybieraj ściany')
        b.clicked.connect(lambda _=False: self._vn_pick('faces'))
        row.addWidget(b)
        b = QPushButton('Wyczyść')
        b.clicked.connect(lambda _=False: self._vn_clear_faces())
        row.addWidget(b)
        s.addLayout(row)
        combo(s, 'multi', vf.MULTI_LABELS, 'top')
        combo(s, 'cross', vf.CROSS_LABELS, 'top')
        combo(s, 'mapping', su.MAPPING_LABELS, 'top')
        combo(s, 'priority', su.PRIORITY_LABELS, 'top')
        # 2. obszar
        s = section('2. Obszar generowania', True)
        self.vn_areas = QListWidget()
        self.vn_areas.setFixedHeight(56)
        self.vn_areas.currentRowChanged.connect(lambda r: self._vn_area_select(r))
        s.addWidget(self.vn_areas)
        row = QHBoxLayout()
        for title, fn in (('Dodaj obszar', self._vn_area_add), ('Usuń obszar', self._vn_area_remove)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        s.addLayout(row)
        combo(s, 'rtype', su.REGION_LABELS, 'region')
        fields(s, REGION_FIELDS, 'region')
        self.vn_region_pick = QPushButton('Wskaż szkic obszaru')
        self.vn_region_pick.clicked.connect(lambda _=False: self._vn_pick('region_sketch'))
        s.addWidget(self.vn_region_pick)
        # 3. biblioteka
        s = section('3. Biblioteka wzorów', True)
        row = QHBoxLayout()
        self.vn_cat = QComboBox()
        self.vn_cat.addItem('Wszystkie kategorie', '')
        self.vn_cat.addItem('★ Ulubione', 'fav')
        for k_, t_ in lib.CATEGORY_LABELS.items():
            self.vn_cat.addItem(t_, k_)
        self.vn_cat.currentIndexChanged.connect(lambda *_: self._vn_library_fill())
        row.addWidget(self.vn_cat)
        s.addLayout(row)
        self.vn_search = QLineEdit()
        self.vn_search.setPlaceholderText('Szukaj wzoru…')
        self.vn_search.textChanged.connect(lambda *_: self._vn_library_fill())
        s.addWidget(self.vn_search)
        self.vn_lib = QListWidget()
        self.vn_lib.setViewMode(QListView.IconMode)
        self.vn_lib.setIconSize(QSize(56, 56))
        self.vn_lib.setGridSize(QSize(78, 92))
        self.vn_lib.setResizeMode(QListView.Adjust)
        self.vn_lib.setWordWrap(True)
        self.vn_lib.setFixedHeight(210)
        self.vn_lib.itemClicked.connect(lambda it: self._vn_library_apply(it))
        s.addWidget(self.vn_lib)
        row = QHBoxLayout()
        b = QPushButton('★ Ulubiony')
        b.clicked.connect(lambda _=False: self._vn_library_fav())
        row.addWidget(b)
        b = QPushButton('Własny ze szkicu')
        b.clicked.connect(lambda _=False: self._vn_pick('custom_sketch'))
        row.addWidget(b)
        b = QPushButton('Import SVG / DXF')
        b.clicked.connect(lambda _=False: self.vent_import_file())
        row.addWidget(b)
        s.addLayout(row)
        # 4. rozmieszczenie
        s = section('4. Rozmieszczenie', True)
        for key, items in COMBOS_AREA[:3]:
            combo(s, key, items, 'area')
        self.vn_link = QCheckBox('Powiąż rozstaw poziomy i pionowy')
        self.vn_link.setChecked(True)
        self.vn_link.toggled.connect(lambda *_: self._vn_changed('link', 'area'))
        s.addWidget(self.vn_link)
        for key, items in COMBOS_AREA[5:8]:
            combo(s, key, items, 'area')
        fields(s, LAYOUT_FIELDS, 'area')
        # 5. wymiary
        s = section('5. Wymiary', True)
        fields(s, SHAPE_FIELDS, 'area')
        for key, items in COMBOS_AREA[9:]:
            combo(s, key, items, 'area')
        fields(s, GEN_FIELDS, 'area')
        self.vn_mixed = QLineEdit()
        self.vn_mixed.setPlaceholderText('Wzór mieszany: kształt w h kąt udział; … (np. circle 4 4 0 1; hex 4 4 30 1)')
        self.vn_mixed.editingFinished.connect(lambda: self._vn_changed('mixed', 'area'))
        s.addWidget(self.vn_mixed)
        # 6. marginesy
        s = section('6. Marginesy i odstępy')
        for key, items in (COMBOS_AREA[3], COMBOS_AREA[4], COMBOS_AREA[8]):
            combo(s, key, items, 'area')
        fields(s, EDGE_FIELDS, 'area')
        # 7. gradienty
        s = section('7. Gradienty')
        self.vn_grad = QLineEdit()
        self.vn_grad.setPlaceholderText('parametr kierunek funkcja od do; … (np. size h linear 1 0.4; rotation radial sin 0 90)')
        self.vn_grad.setToolTip('Parametry: ' + ', '.join(vl.GRAD_PARAMS) + '\nKierunki: ' + ', '.join(vl.GRAD_DIRS) +
                                '\nFunkcje: ' + ', '.join(vl.GRAD_FUNCS) + ' (custom: dodaj „t:v,t:v”)')
        self.vn_grad.editingFinished.connect(lambda: self._vn_changed('gradients', 'area'))
        s.addWidget(self.vn_grad)
        self.vn_grad_info = _label('', 'value')
        self.vn_grad_info.setWordWrap(True)
        s.addWidget(self.vn_grad_info)
        # 8-9. kierunek, głębokość, fazowanie
        s = section('8. Kierunek i głębokość')
        for key, items in COMBOS_CUT[:3]:
            combo(s, key, items, 'cut')
        self.vn_reverse = QCheckBox('Odwróć kierunek wykonywania')
        self.vn_reverse.toggled.connect(lambda *_: self._vn_changed('reverse', 'cut'))
        s.addWidget(self.vn_reverse)
        self.vn_vec = QLineEdit('0 0 -1')
        self.vn_vec.setToolTip('Wektor kierunku (x y z) - tryb „Wektor użytkownika” / oś')
        self.vn_vec.editingFinished.connect(lambda: self._vn_changed('vector', 'cut'))
        s.addWidget(self.vn_vec)
        b = QPushButton('Wskaż powierzchnię końcową')
        b.clicked.connect(lambda _=False: self._vn_pick('end_face'))
        s.addWidget(b)
        for key, items in COMBOS_CUT[3:]:
            combo(s, key, items, 'cut')
        s = section('9. Fazowanie i zaokrąglenia')
        fields(s, CUT_FIELDS, 'cut')
        # 10. strefy zabronione
        s = section('10. Strefy zabronione')
        self.vn_zones = QListWidget()
        self.vn_zones.setFixedHeight(64)
        s.addWidget(self.vn_zones)
        row = QHBoxLayout()
        for title, fn in (('Komponent', lambda: self._vn_pick('zone_comp')), ('Szkic', lambda: self._vn_pick('zone_sketch')),
                          ('Prostokąt', lambda: self._vn_zone_add('rect')), ('Usuń', self._vn_zone_remove)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        s.addLayout(row)
        self.vn_zone_note = _label('Istniejące otwory ściany i elementy za ścianką (słupki, żebra, przegrody) są wykrywane samoczynnie.', 'value')
        self.vn_zone_note.setWordWrap(True)
        s.addWidget(self.vn_zone_note)
        # 11. edycja pojedynczych otworów
        s = section('11. Edycja pojedynczych otworów')
        row = QHBoxLayout()
        for title, key in (('Zaznaczaj otwory', 'edit'), ('Dodawaj otwory', 'add')):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, k_=key: self._vn_pick(k_))
            row.addWidget(b)
        s.addLayout(row)
        self.vn_sel = _label('Zaznaczone: 0', 'value')
        s.addWidget(self.vn_sel)
        grid = QGridLayout()
        self.vn_ed = {}
        for n, (key, title, val, lo, hi) in enumerate((('dx', 'Przesuń X', 0.0, -1e3, 1e3), ('dy', 'Przesuń Y', 0.0, -1e3, 1e3), ('rot', 'Obróć', 0.0, -360, 360),
                                                       ('w', 'Wymiar w', 0.0, 0, 1e3), ('h', 'Wymiar h', 0.0, 0, 1e3), ('depth_k', 'Głębokość ×', 1.0, .01, 10),
                                                       ('tilt', 'Nachylenie', 0.0, -80, 80))):
            box = _spin(val, lo, hi, 2, .5, '')
            grid.addWidget(_label(title, 'label'), n // 2, (n % 2) * 2)
            grid.addWidget(box, n // 2, (n % 2) * 2 + 1)
            self.vn_ed[key] = box
        s.addLayout(grid)
        self.vn_ed_kind = QComboBox()
        self.vn_ed_kind.addItem('(kształt bez zmian)', '')
        for k_, t_ in vs.SHAPE_LABELS.items():
            if k_ != 'custom':
                self.vn_ed_kind.addItem(t_, k_)
        s.addWidget(self.vn_ed_kind)
        row = QHBoxLayout()
        for title, fn in (('Zastosuj do zaznaczonych', self._vn_edit_apply), ('Usuń', lambda: self._vn_edit_flag('deleted', True)),
                          ('Przywróć', self._vn_edit_restore), ('Zablokuj', lambda: self._vn_edit_flag('locked', True))):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        s.addLayout(row)
        # 12. zaawansowane
        s = section('12. Parametry zaawansowane')
        self.vn_islands = QCheckBox('Zezwól na niepołączone fragmenty materiału')
        self.vn_islands.toggled.connect(lambda *_: self._vn_changed('allow_islands', 'top'))
        s.addWidget(self.vn_islands)
        fields(s, (('density', 'Gęstość materiału (masa)', 0.0, 0, 30, 3, .1, ' g/cm³'), ('map_rotate', 'Obrót odwzorowania', 0.0, -360, 360, 1, 5, ' °')), 'top')
        # 13-14. statystyki, podgląd
        s = section('13. Statystyki', True)
        self.vn_stats = _label('', 'value')
        self.vn_stats.setWordWrap(True)
        s.addWidget(self.vn_stats)
        s = section('14. Podgląd', True)
        self.vn_level = QComboBox()
        for k_, t_ in LEVEL_LABELS.items():
            self.vn_level.addItem(t_, k_)
        self.vn_level.currentIndexChanged.connect(lambda *_: self._vn_update())
        s.addWidget(self.vn_level)
        self.vn_auto = QCheckBox('Po zmianie parametrów przelicz dokładny podgląd')
        s.addWidget(self.vn_auto)
        self.vn_bar = QProgressBar()
        self.vn_bar.setRange(0, 100)
        s.addWidget(self.vn_bar)
        row = QHBoxLayout()
        for title, fn in (('Przelicz podgląd', lambda: self._vn_preview(force=True)), ('Przerwij', lambda: _STATE.update(cancel=True))):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        s.addLayout(row)
        row = QHBoxLayout()
        for title, fn in (('Resetuj parametry', self.vent_reset), ('Wycentruj wzór', self.vent_centre)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        lay.addLayout(row)
        row = QHBoxLayout()
        for title, fn in (('Zapisz szablon', self.vent_save_template), ('Wczytaj szablon', self.vent_load_template)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        lay.addLayout(row)
        self.vn_info = _label('', 'value')
        self.vn_info.setWordWrap(True)
        lay.addWidget(self.vn_info)
        self.vn_status = _label('Kliknij ścianę bryły.', 'status')
        self.vn_status.setWordWrap(True)
        lay.addWidget(self.vn_status)
        self.vn_apply, _ = self._buttons(self.vn_panel.footer, 'Zastosuj', 'Anuluj', self.apply_vent, lambda: self.set_mode(None))
        self._vn_lib_cache = {}
        return self.vn_panel

    @staticmethod
    def _vent_fresh():
        return dict(target=None, faces=[], areas=[copy.deepcopy(lib.preset('circle'))], cur=0, cut=dict(vf.CUT_DEFAULTS), multi='independent',
                    cross='stop', mapping='auto', priority='shape', exclusions=[], pick='faces', sel=set(), result=None, top=dict(density=0.0, map_rotate=0.0, allow_islands=False),
                    end_face=None, out_ids=[])

    # ------------------------------------------------------------------ cykl życia
    def _vent_begin(self):
        self.vn = self._vent_fresh()
        self._vn_cache = self._vn_done = None
        self.vn_panel.show()
        self._vn_sync_widgets()
        self._vn_library_fill()
        self.hint('Wentylacja: kliknij ścianę bryły (Shift - kolejne). Wybierz wzór z biblioteki i ustaw parametry; Enter - Zastosuj.')
        self.view.setCursor(Qt.PointingHandCursor)
        self._vn_update()

    def _vn_pick(self, what):
        self.vn['pick'] = what
        self.vn_status.setText({'faces': 'Klikaj ściany (Shift - dodaj).', 'region_sketch': 'Kliknij szkic z konturem obszaru.',
                                'custom_sketch': 'Kliknij szkic z konturem własnego wzoru.', 'zone_comp': 'Kliknij komponent - strefa zabroniona.',
                                'zone_sketch': 'Kliknij szkic - strefa zabroniona.', 'edit': 'Klikaj otwory (Shift - kolejne).',
                                'add': 'Klikaj miejsca nowych otworów na ścianie.', 'end_face': 'Kliknij powierzchnię końcową otworów.'}.get(what, ''))

    def vent_hover(self, x, y):
        if self.vn.get('pick', 'faces') == 'faces':
            self._hover_one_face(x, y)
            return
        self._hover_one_key = None
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        self.view.set_hover_mesh(body.mesh if body is not None and self.vn.get('pick') in ('faces', 'zone_comp', 'region_sketch', 'zone_sketch', 'custom_sketch') else None)

    def vent_click(self, x, y, shift=False):
        pick = self.vn.get('pick', 'faces')
        if pick in ('region_sketch', 'zone_sketch', 'custom_sketch'):
            hit = self.view.pick_body(x, y) if hasattr(self.view, 'pick_body') else None
            bid = hit if isinstance(hit, str) else (hit[0] if hit else None)
            body = self.document.get(bid) if bid else None
            if body is None:
                hit2 = self.view.pick_face(x, y)
                body = self.document.get(hit2[0]) if hit2 else None
            if body is None or body.kind != 'sketch':
                self.toast('Kliknij szkic (zamknięty kontur).')
                return
            if pick == 'region_sketch':
                a = self._vn_area()
                a['region'] = dict(a.get('region') or {}, type=a.get('region', {}).get('type') if a.get('region', {}).get('type') in ('sketch', 'contours', 'between', 'edges') else 'sketch',
                                   sketch=body.id)
            elif pick == 'zone_sketch':
                self.vn['exclusions'].append(dict(type='sketch', id=body.id, name=body.name))
            else:
                self.vent_custom_from_sketch(body)
            self.vn['pick'] = 'faces'
            self._vn_sync_widgets()
            self._vn_update()
            return
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None:
            return
        P, N = np.asarray(hit[2], float), np.asarray(hit[1], float)
        if pick == 'zone_comp':
            if body.id == self.vn.get('target'):
                self.toast('Komponent to inna bryła niż ta z wentylacją.')
                return
            self.vn['exclusions'].append(dict(type='component', id=body.id, name=body.name))
            self.vn['pick'] = 'faces'
            self._vn_sync_widgets()
            self._vn_update()
            return
        if pick in ('edit', 'add'):
            self._vn_edit_click(P, shift, add=pick == 'add')
            return
        if body.kind != 'solid':
            self.toast('Wentylację wycina się w bryle - kliknij ścianę bryły.')
            return
        try:
            f, n = kernel.face_at(body.shape, N, P, curved=True)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        fw = f.wrapped if hasattr(f, 'wrapped') else f
        ref = vf.face_refs(body.shape, [fw])[0]
        ref['point'], ref['normal'] = [float(v) for v in P], [float(v) for v in (n if n is not None else N)]
        if pick == 'end_face':
            self.vn['end_face'] = ref
            self.vn['pick'] = 'faces'
            self._vn_update()
            return
        if self.vn.get('target') not in (None, body.id) and not shift:
            self.vn['faces'] = []
        if self.vn.get('target') != body.id:
            self.vn['faces'] = []
        self.vn['target'] = body.id
        if not shift:
            self.vn['faces'] = []
        if not any(np.allclose(r['centroid'], ref['centroid'], atol=1e-6) for r in self.vn['faces']):
            self.vn['faces'].append(ref)
        self._vn_update()

    # ------------------------------------------------------------------ obszary i pola
    def _vn_area(self):
        return self.vn['areas'][self.vn['cur']]

    def _vn_area_add(self):
        self.vn['areas'].append(copy.deepcopy(self._vn_area()))
        self.vn['cur'] = len(self.vn['areas']) - 1
        self._vn_sync_widgets()
        self._vn_update()

    def _vn_area_remove(self):
        if len(self.vn['areas']) > 1:
            del self.vn['areas'][self.vn['cur']]
            self.vn['cur'] = max(0, self.vn['cur'] - 1)
        self._vn_sync_widgets()
        self._vn_update()

    def _vn_area_select(self, r):
        if 0 <= r < len(self.vn['areas']) and r != self.vn['cur']:
            self.vn['cur'] = r
            self._vn_sync_widgets()

    def _vn_changed(self, key, group):
        if getattr(self, '_vn_syncing', False):
            return
        a = self._vn_area()
        if group == 'area':
            if key == 'link':
                a['link'] = self.vn_link.isChecked()
            elif key == 'mixed':
                a['mixed'] = _parse_mixed(self.vn_mixed.text())
            elif key == 'gradients':
                try:
                    a['gradients'] = _parse_gradients(self.vn_grad.text())
                    self.vn_grad_info.setText(f'Gradientów: {len(a["gradients"])}')
                except ValueError as exc:
                    self.vn_grad_info.setText(str(exc))
                    return
            elif key in self.vn_c:
                a[key] = self.vn_c[key][0].currentData()
            else:
                box = self.vn_w[('area', key)][1]
                a[key] = int(box.value()) if box.decimals() == 0 else float(box.value())
                if key == 'px' and a.get('link'):
                    a['py'] = 0.0
        elif group == 'region':
            r = dict(a.get('region') or {'type': 'face'})
            if key == 'rtype':
                r['type'] = self.vn_c['rtype'][0].currentData()
            else:
                box = self.vn_w[('region', key)][1]
                r[key] = int(box.value()) if box.decimals() == 0 else float(box.value())
            a['region'] = r
        elif group == 'cut':
            if key == 'reverse':
                self.vn['cut']['reverse'] = self.vn_reverse.isChecked()
            elif key == 'vector':
                try:
                    v = [float(t.replace(',', '.')) for t in self.vn_vec.text().split()]
                    self.vn['cut']['vector'] = v if len(v) == 3 and np.linalg.norm(v) > 0 else None
                except ValueError:
                    pass
            elif key in self.vn_c:
                self.vn['cut'][key] = self.vn_c[key][0].currentData()
            else:
                self.vn['cut'][key] = float(self.vn_w[('cut', key)][1].value())
        else:
            if key in self.vn_c:
                self.vn[key] = self.vn_c[key][0].currentData()
            elif key == 'allow_islands':
                self.vn['top']['allow_islands'] = self.vn_islands.isChecked()
            else:
                self.vn['top'][key] = float(self.vn_w[('top', key)][1].value())
        self._vn_visibility()
        self._vn_update()

    def _vn_sync_widgets(self):
        """Pola okna z bieżącego obszaru i ustawień cięcia (bez sygnałów)."""
        self._vn_syncing = True
        try:
            a = dict(vl.DEFAULTS, **self._vn_area())
            r = dict(a.get('region') or {'type': 'face'})
            for (group, key), (_l, box) in self.vn_w.items():
                src = a if group == 'area' else (r if group == 'region' else (self.vn['cut'] if group == 'cut' else self.vn['top']))
                if key in src and src[key] is not None and not isinstance(src[key], (list, dict)):
                    box.setValue(float(src[key]))
            for key, (box, group) in self.vn_c.items():
                val = {'area': a.get(key), 'region': r.get('type', 'face'), 'cut': self.vn['cut'].get(key), 'top': self.vn.get(key)}[group] if key != 'rtype' else r.get('type', 'face')
                if val is not None:
                    box.setCurrentIndex(max(0, box.findData(val)))
            self.vn_link.setChecked(bool(a.get('link', True)))
            self.vn_reverse.setChecked(bool(self.vn['cut'].get('reverse')))
            self.vn_islands.setChecked(bool(self.vn['top'].get('allow_islands')))
            self.vn_mixed.setText('; '.join(f'{m["kind"]} {m.get("w", a["w"]):g} {m.get("h", m.get("w", a["h"])):g} {m.get("angle", 0):g} {m.get("share", 1):g}' for m in a.get('mixed') or []))
            self.vn_grad.setText(_format_gradients(a.get('gradients') or []))
            self.vn_areas.blockSignals(True)
            self.vn_areas.clear()
            for n, ar in enumerate(self.vn['areas']):
                rr = (ar.get('region') or {}).get('type', 'face')
                self.vn_areas.addItem(f'Obszar {n + 1}: {su.REGION_LABELS.get(rr, rr)} - {vs.SHAPE_LABELS.get(ar.get("kind"), ar.get("generator") or "")}')
            self.vn_areas.setCurrentRow(self.vn['cur'])
            self.vn_areas.blockSignals(False)
            self.vn_zones.clear()
            for z in self.vn['exclusions']:
                self.vn_zones.addItem(f'{z.get("type")}: {z.get("name", "")}')
        finally:
            self._vn_syncing = False
        self._vn_visibility()

    def _vn_visibility(self):
        """Tylko parametry mające zastosowanie do wybranego wzoru, układu, obszaru i rodzaju otworu."""
        a = dict(vl.DEFAULTS, **self._vn_area())
        gen = a.get('generator') or ''
        used = set()
        if gen:
            used |= set(GEN_USE.get(gen, ()))
        else:
            used |= set(vs.SHAPE_PARAMS.get(a['kind'], ('w',)))
            used |= set(LAYOUT_USE.get(a['layout'], ()))
            used |= {'hole_angle', 'seed'} if a['layout'] in ('random', 'gradient') else {'hole_angle'}
            if a['layout'] == 'radial':
                used.add('arms_n')
        if a.get('fill') == 'B':
            used |= {'rows', 'cols', 'count'}
        if a.get('fill') == 'D':
            used |= {'target_open', 'size_min', 'size_max'}
        rt = (a.get('region') or {}).get('type', 'face')
        for (group, key), (lab, box) in self.vn_w.items():
            if group == 'area' and key in dict((f[0], 1) for f in SHAPE_FIELDS + LAYOUT_FIELDS + GEN_FIELDS):
                vis = key in used
            elif group == 'area':
                vis = key not in ('target_open', 'size_min', 'size_max') or a.get('fill') == 'D'
                if key in ('min_area', 'min_width'):
                    vis = a.get('edge_mode') == 'trim'
                if key == 'min_scale':
                    vis = a.get('edge_mode') in ('shrink', 'adaptive') or a.get('fill') == 'F'
            elif group == 'region':
                vis = key in REGION_USE.get(rt, ())
            elif group == 'cut':
                ht, dm, dr = self.vn['cut'].get('hole_type'), self.vn['cut'].get('depth_mode'), self.vn['cut'].get('direction')
                vis = {'depth': dm in ('depth', 'both', 'symmetric') or ht in ('blind', 'recess'), 'depth2': dm == 'both', 'dir_angle': dr == 'angle',
                       'tilt': ht in ('tilted', 'channel'), 'size_in': ht in ('conical', 'variable', 'widen_in', 'widen_out'),
                       'size_out': ht in ('conical', 'variable', 'widen_in', 'widen_out'), 'size_mid': ht == 'variable',
                       'step_depth': ht == 'stepped', 'step_scale': ht == 'stepped', 'chamfer': ht in ('chamfer1', 'chamfer2', 'rounded'),
                       'louver_angle': ht in ('louver_out', 'louver_in'), 'louver_h': ht in ('louver_out', 'louver_in'),
                       'louver_t': ht in ('louver_out', 'louver_in'), 'obstacle_factor': dm == 'wall'}.get(key, True)
            else:
                vis = True
            lab.setVisible(vis)
            box.setVisible(vis)
        for key, (box, group) in self.vn_c.items():
            if group == 'area':
                vis = {'mix_mode': bool(a.get('mixed')), 'mirror_axis': a['layout'] == 'mirror' and not gen,
                       'twist': (a['layout'] == 'spiral' and not gen) or gen in ('spiral', 'turbine'), 'adjust': a.get('fill') == 'D',
                       'vmode': gen == 'voronoi', 'fan_style': gen == 'fan', 'kind': not gen or gen in ('fan', 'fractal'), 'layout': not gen}.get(key, True)
                box.setVisible(vis)
            elif group == 'cut' and key == 'louver_dir':
                box.setVisible(self.vn['cut'].get('hole_type') in ('louver_out', 'louver_in'))
        self.vn_region_pick.setVisible(rt in ('sketch', 'contours', 'between', 'edges'))
        self.vn_vec.setVisible(self.vn['cut'].get('direction') in ('vector', 'edge', 'axis', 'radial'))

    # ------------------------------------------------------------------ biblioteka
    def _vn_library_fill(self):
        if not hasattr(self, 'vn_lib'):
            return
        cat, text = self.vn_cat.currentData(), self.vn_search.text().strip().lower()
        favs = set(lib.favorites())
        self.vn_lib.clear()
        entries = [dict(e, user=False) for e in lib.PATTERNS] + [dict(id='tpl:' + t['name'], cat='user', label=t['name'], params=(t.get('config') or {}).get('area') or {},
                                                                    user=True, thumb=t.get('thumb'), fav=t.get('favorite')) for t in lib.templates()]
        for e in entries:
            if cat == 'fav' and not (e['id'] in favs or e.get('fav')):
                continue
            if cat and cat != 'fav' and e['cat'] != cat:
                continue
            if text and text not in e['label'].lower():
                continue
            it = QListWidgetItem(('★ ' if (e['id'] in favs or e.get('fav')) else '') + e['label'])
            it.setData(Qt.UserRole, e['id'])
            it.setIcon(self._vn_thumb(e))
            self.vn_lib.addItem(it)

    def _vn_thumb(self, e):
        """Ikona wzoru: z pamięci / pliku zapisanego w szablonie od razu, a narysowana z generatora - w kolejce w tle (z zapisem na dysk)."""
        key = e['id']
        if key not in self._vn_lib_cache:
            if e.get('thumb'):
                import base64
                pm = QPixmap()
                pm.loadFromData(base64.b64decode(e['thumb']), 'PNG')
                self._vn_lib_cache[key] = QIcon(pm)
            else:
                from . import thumbcache as tc
                if not hasattr(self, '_thumb_queue'):
                    self._thumb_queue = tc.Queue()
                params = e['params']
                self._thumb_queue.add(self._vn_lib_cache, key, lambda params=params: tc.cached_pixmap('vent', params, 64, lambda: lib.thumbnail(params)), self.vn_lib)
                return tc.placeholder(64)
        return self._vn_lib_cache[key]

    def _vn_library_apply(self, item):
        pid = item.data(Qt.UserRole)
        if pid.startswith('tpl:'):
            t = next((x for x in lib.templates() if x['name'] == pid[4:]), None)
            if t:
                self._vn_apply_config(t.get('config') or {})
            return
        params = lib.preset(pid)
        if params.get('generator') == 'gyroid3d':
            self.vn_status.setText('Gyroid 3D: struktura przestrzenna - parametry w sekcji Wymiary (komórka); wynik to fasetowa bryła B-Rep.')
        a = self._vn_area()
        keep = {k: a[k] for k in ('region', 'overrides', 'added') if k in a}
        new = dict(vl.DEFAULTS)
        new.update(params)
        louver = new.pop('louver', False)
        if louver:
            self.vn['cut']['hole_type'] = 'louver_out'
        elif self.vn['cut'].get('hole_type') in ('louver_out', 'louver_in'):
            self.vn['cut']['hole_type'] = 'through'
        if 'region' in params:
            keep['region'] = params['region']
        new.update(keep)
        new['pattern_id'] = pid
        self.vn['areas'][self.vn['cur']] = new
        self._vn_sync_widgets()
        self._vn_update()

    def _vn_library_fav(self):
        it = self.vn_lib.currentItem()
        if it is None:
            return
        pid = it.data(Qt.UserRole)
        if pid.startswith('tpl:'):
            t = next((x for x in lib.templates() if x['name'] == pid[4:]), None)
            lib.set_template_favorite(pid[4:], not (t or {}).get('favorite'))
        else:
            lib.set_favorite(pid, pid not in lib.favorites())
        self._vn_library_fill()

    def vent_custom_from_sketch(self, body):
        """Własny wzór: zamknięte kontury szkicu (z otworami wewnętrznymi) jako kształt otworu w układzie szkicu."""
        loops3 = vf._sketch_loops(body)
        if not loops3:
            raise kernel.CadError('Szkic nie ma zamkniętych konturów.')
        P = np.vstack(loops3)
        c = P.mean(0)
        u, s_, vt = np.linalg.svd(P - c)
        x, y = vt[0], vt[1]
        loops = [[('S', [((q - c) @ x, (q - c) @ y) for q in lp])] for lp in loops3]
        loops = _check_custom(loops)
        a = self._vn_area()
        a.update(kind='custom', generator='', loops=loops, fit=True)
        self._vn_sync_widgets()
        self._vn_update()

    def vent_import_file(self, path=None):
        """Import wzoru z SVG / DXF: krawędzie → kontury (łączenie, zamykanie małych przerw, usuwanie duplikatów),
        kontrola: otwarte kontury, samoprzecięcia, nakładające się krzywe, fragmenty zerowej długości."""
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self, 'Wzór otworu z pliku', '', 'Rysunki (*.svg *.dxf)')
            if not path:
                return None
        loops, report = import_pattern(path)
        a = self._vn_area()
        a.update(kind='custom', generator='', loops=loops, fit=True)
        self.vn_status.setText('; '.join(t for _l, t in report))
        self._vn_sync_widgets()
        self._vn_update()
        return report

    # ------------------------------------------------------------------ strefy
    def _vn_zone_add(self, kind):
        self.vn['exclusions'].append(dict(type=kind, cx=0.0, cy=0.0, w=10.0, h=10.0, d=10.0, name='strefa ręczna'))
        self._vn_sync_widgets()
        self._vn_update()

    def _vn_zone_remove(self):
        r = self.vn_zones.currentRow()
        if 0 <= r < len(self.vn['exclusions']):
            del self.vn['exclusions'][r]
        self._vn_sync_widgets()
        self._vn_update()

    # ------------------------------------------------------------------ edycja pojedynczych otworów
    def _vn_hole_at(self, P):
        res = self.vn.get('result')
        if not res or not res.get('plan'):
            return None
        best = None
        for pl in res['plan']['plans']:
            m = pl['mappers'][0]
            try:
                q = m.to2d(P)
            except kernel.CadError:
                continue
            for h in pl['holes']:
                d = float(np.linalg.norm(np.asarray(h['c'], float) - q))
                r = max(h.get('w', 1.0), h.get('h', 1.0)) / 2 + 1.0
                if d <= r and (best is None or d < best[0]):
                    best = (d, pl['area'], h['key'], q)
        return best

    def _vn_edit_click(self, P, shift, add=False):
        if add:
            res = self.vn.get('result')
            if not res or not res.get('plan'):
                return
            m = res['plan']['plans'][0]['mappers'][0]
            q = m.to2d(P)
            a = self._vn_area()
            a.setdefault('added', []).append(dict(key=f'add/{uuid.uuid4().hex[:8]}', c=[float(q[0]), float(q[1])], kind=a.get('kind', 'circle'),
                                                  w=float(a.get('w', 4.0)), h=float(a.get('h', 4.0)), locked=True))
            self._vn_update()
            return
        hit = self._vn_hole_at(P)
        if hit is None:
            if not shift:
                self.vn['sel'] = set()
        else:
            key = (hit[1], hit[2])
            if not shift:
                self.vn['sel'] = {key}
            else:
                self.vn['sel'] ^= {key}
        self.vn_sel.setText(f'Zaznaczone: {len(self.vn["sel"])}')
        self._vn_show(self.vn.get('result'))

    def _vn_edit_apply(self):
        for ai, key in self.vn['sel']:
            ov = self.vn['areas'][ai].setdefault('overrides', {}).setdefault(key, {})
            for k_ in ('dx', 'dy', 'rot', 'depth_k', 'tilt'):
                v = float(self.vn_ed[k_].value())
                if (k_ == 'depth_k' and abs(v - 1) > 1e-9) or (k_ != 'depth_k' and abs(v) > 1e-9):
                    ov[k_] = v
            for k_ in ('w', 'h'):
                if self.vn_ed[k_].value() > 0:
                    ov[k_] = float(self.vn_ed[k_].value())
            if self.vn_ed_kind.currentData():
                ov['kind'] = self.vn_ed_kind.currentData()
        self._vn_update()

    def _vn_edit_flag(self, flag, val):
        for ai, key in self.vn['sel']:
            self.vn['areas'][ai].setdefault('overrides', {}).setdefault(key, {})[flag] = val
        self._vn_update()

    def _vn_edit_restore(self):
        for ai, key in self.vn['sel']:
            self.vn['areas'][ai].setdefault('overrides', {}).pop(key, None)
        self._vn_update()

    # ------------------------------------------------------------------ przepis, podgląd
    def vent_recipe(self):
        if not self.vn.get('target') or not self.vn.get('faces'):
            return None
        r = vf.new_recipe(self.vn['target'], [dict(f) for f in self.vn['faces']], areas=copy.deepcopy(self.vn['areas']),
                          multi=self.vn['multi'], cross=self.vn['cross'], mapping=self.vn['mapping'], priority=self.vn['priority'],
                          cut=dict(self.vn['cut']), exclusions=copy.deepcopy(self.vn['exclusions']), density=self.vn['top'].get('density', 0.0),
                          map_rotate=self.vn['top'].get('map_rotate', 0.0), allow_islands=self.vn['top'].get('allow_islands', False))
        if self.vn['priority'] in ('spacing', 'proportion'):
            r['cut']['profile_mode'] = 'mapped'
        if self.vn.get('end_face'):
            r['end_face'] = self.vn['end_face']
        return r

    def _vn_update(self):
        if not hasattr(self, 'vn_c') or self.mode != 'vent':
            return
        tb = self.document.get(self.vn.get('target') or '')
        n = len(self.vn['faces'])
        self.vn_step1.set_state('done' if n else 'active', f'{tb.name if tb else ""}: {n} ścian' if n else 'kliknij ścianę')
        self.vn_faces.setText(f'Zaznaczone ściany: {n}' + (f' ({", ".join(sorted({f.get("kind", "") for f in self.vn["faces"]}))})' if n else '') +
                              ('' if n else ' - kliknij ścianę bryły (Shift - kolejne).'))
        self.vn_apply.setEnabled(False)
        self._vn_timer.stop()
        if self.vent_recipe() is None:
            self.view.set_preview_mesh(None)
            return
        self.vn_status.setText('Liczenie podglądu…')
        self._vn_timer.start()

    def _vn_preview(self, force=False):
        recipe = self.vent_recipe()
        if recipe is None or self.mode != 'vent':
            return
        level = self.vn_level.currentData()
        if force and level == 'fast' and self.vn_auto.isChecked():
            level = 'exact'
        bodies = list(self.document.bodies)
        sig = (vf.signature(bodies, recipe), level)
        done = getattr(self, '_vn_done', None)
        if not force and done is not None and done['sig'] == sig and self.vn.get('result') is not None:
            self.vn_apply.setEnabled(done['ok'])       # nic się nie zmieniło od ostatniego podglądu - nie liczy się od nowa
            self.vn_status.setText(done['status'])
            return
        self._vn_sig = sig
        token = self._vn_token = object()            # nowe żądanie przerywa liczenie poprzedniego
        cancelled = lambda: _STATE['cancel'] or self._vn_token is not token
        _STATE.update(cancel=False, progress=0.0)
        reuse = getattr(self, '_vn_cache', None)
        reuse = reuse['value'] if reuse and reuse['base'] == sig[0] else None

        def compute():
            gen = (recipe['areas'][0].get('generator') or '')
            if gen == 'gyroid3d':
                return dict(gyroid=self._vn_gyroid(bodies, recipe, level == 'exact'), level=level)
            if level == 'fast':
                pl = reuse['plan'] if reuse and reuse.get('plan') is not None and reuse.get('tools') is None and not reuse.get('holes_done') else vf.plan(bodies, recipe, cancel=cancelled)
                holes = [h for p_ in pl['plans'] for h in p_['holes']]
                for h in holes:
                    if h['status'] in ('ok', 'adjust'):
                        h['tool'] = 0
                st = vf._stats_plan(pl, holes, recipe)
                return dict(plan=pl, holes=holes, stats=st, report=pl['report'] + [r_ for p_ in pl['plans'] for r_ in []], level=level, meshes=_outline_meshes(pl))
            res = vf.build(bodies, recipe, cancel=cancelled, progress=lambda f: _STATE.update(progress=f), exact=level == 'exact', pre=reuse)
            res['level'] = level
            res['meshes'] = _outline_meshes(res['plan'])
            if level == 'spatial':
                import cadquery as cq
                from .enclosure import merge_meshes
                flat = []
                for t in res['tools'][:1500]:
                    flat += t if isinstance(t, list) else [t]
                res['tool_mesh'] = merge_meshes([kernel.display_mesh(cq.Shape.cast(t)) for t in flat])
            elif res.get('shape') is not None:
                res['result_mesh'] = kernel.display_mesh(res['shape'])
            return res

        def show(value, error):
            self._vn_poll.stop()
            if self.mode != 'vent' or getattr(self, '_vn_sig', None) != sig:
                return
            if error or value is None:                                    # ostatnia poprawna geometria zostaje
                self.vn_status.setText((str(error) if error else 'Nie udało się.') + (' Podgląd: ostatni poprawny wynik.' if self.vn.get('result') else ''))
                self.vn_apply.setEnabled(False)
                return
            self.vn['result'] = value
            self._vn_show(value)
            self.vn_apply.setEnabled(bool(value.get('gyroid') or value.get('stats', {}).get('count')))
            self.vn_status.setText('Enter albo Zastosuj wycina otwory.' if self.vn_apply.isEnabled() else 'Żaden otwór nie spełnia wymagań.')
            self._vn_done = dict(sig=sig, ok=self.vn_apply.isEnabled(), status=self.vn_status.text())
            old = getattr(self, '_vn_cache', None)
            keep = old['value'] if old and old['base'] == sig[0] else None
            # najpełniejszy wynik tego zadania do ponownego użycia przez Zastosuj: gotowy kształt > narzędzia > nic
            if not value.get('gyroid') and (value.get('shape') is not None or value.get('tools') is not None or keep is None):
                self._vn_cache = dict(base=sig[0], value=value)
            if level == 'fast' and self.vn_auto.isChecked():
                self.vn_level.blockSignals(True)
                self._vn_auto_exact = True
                self.vn_level.blockSignals(False)
        self._vn_poll.start()
        self.run_preview('vent', compute, show)

    def _vn_gyroid(self, bodies, recipe, exact):
        from . import vent_gyroid as gy
        tb = {b.id: b for b in bodies}[recipe['target']]
        a = recipe['areas'][0]
        gp = dict(gy.DEFAULTS, cell=float(a.get('cell', 10.0)), **{k: a[k] for k in gy.DEFAULTS if k in a})
        if not exact:
            import cadquery as cq
            bb = cq.Shape.cast(tb.shape.wrapped).BoundingBox()
            V, T = gy.mesh(np.array([bb.xmin, bb.ymin, bb.zmin]), np.array([bb.xmax, bb.ymax, bb.zmax]), dict(gp, accuracy=4), lambda: _STATE['cancel'])
            return dict(mesh=kernel.DisplayMesh(V.astype(np.float32), T.astype(np.uint32), {}, tuple(V.mean(0)), float(np.ptp(V, axis=0).max())), report=[('ok', f'Szybki podgląd: {len(T)} trójkątów (pomocniczo).')])
        res, rep = gy.build(tb.shape.wrapped, gp, cancel=lambda: _STATE['cancel'])
        import cadquery as cq
        return dict(mesh=kernel.display_mesh(cq.Shape.cast(res)), report=rep, shape=res)

    def _vn_show(self, value):
        if value is None:
            return
        if value.get('gyroid'):
            g = value['gyroid']
            self.view.set_layers_preview([(g['mesh'], (.3, .75, .45, .35), (.05, .4, .2, 1), 1.0)])
            self.vn_info.setText('\n'.join(t for _l, t in g['report']))
            return
        layers = []
        meshes = value.get('meshes') or {}
        sel = self.vn.get('sel') or set()
        for st in ('skip', 'bad', 'adjust', 'ok', 'zone'):
            m = meshes.get(st)
            if m is not None:
                fill, line = COLORS[st]
                layers.append((m, fill, line, 2.2 if st == 'zone' else 1.4))
        if sel and value.get('plan'):
            sm = _outline_meshes(value['plan'], only=sel).get('sel')
            if sm is not None:
                layers.append((sm, (.2, .45, .95, .3), (.1, .3, .9, 1), 2.6))
        if value.get('tool_mesh') is not None:
            layers.append((value['tool_mesh'], (.95, .55, .15, .45), (.7, .35, .05, 1), 1.0))
        if value.get('result_mesh') is not None:
            layers.append((value['result_mesh'], (.35, .6, .95, .5), (.1, .3, .6, 1), 1.0))
        self.view.set_layers_preview(layers)
        st = value.get('stats') or {}
        lines = [f'Otwory: {st.get("count", 0)} (dopasowane {st.get("adjusted", 0)}), pominięte: {st.get("skipped", 0)}, niepoprawne: {st.get("bad", 0)}',
                 f'Pole obszaru: {st.get("region_area", 0):.1f} mm², otwarte (plan): {st.get("open_plan", 0):.1f} mm² ({st.get("open_percent_plan", 0):.1f} %)']
        if st.get('min_bridge') is not None:
            lines.append(f'Najmniejszy mostek: {st["min_bridge"]:.2f} mm, najmniejsza odległość od krawędzi: {(st.get("min_edge") or 0):.2f} mm')
        if 'removed' in st:
            lines.append(f'Po wycięciu (geometria rzeczywista): otwarte na wejściu {st["open_entry"]:.1f} mm²'
                         + (f' ({st["open_percent"]:.1f} %)' if 'open_percent' in st else '') + f', usunięto {st["removed"]:.1f} mm³, zostaje {st["remaining"]:.1f} mm³'
                         + (f', zmiana masy {st["mass_change"]:.2f} g' if 'mass_change' in st else ''))
        lines.append('Powierzchnia otwarta nie jest wynikiem analizy przepływu - nie oznacza wydajności chłodzenia.')
        self.vn_stats.setText('\n'.join(lines))
        self.vn_info.setText('\n'.join(t for _l, t in (value.get('report') or [])[:8]))
        self._vn_handles(value)

    # ------------------------------------------------------------------ manipulatory
    def _vn_handles(self, value):
        pl = (value or {}).get('plan')
        if not pl or not pl['plans']:
            self.view.set_handles([])
            return
        p0 = pl['plans'][0]
        m = p0['mappers'][0]
        c2 = p0['region'].centroid()
        try:
            P, N, X, Y = m.to3d(c2)
        except kernel.CadError:
            return
        a = self._vn_area()
        L = max(8.0, float(a.get('w', 4.0)) * 2)
        self.view.set_handles([dict(id='vent:x', start=P, tip=P + X * L, dir=X, label='Przesuń', min_px=36, color=(.2, .5, .9, 1)),
                               dict(id='vent:y', start=P, tip=P + Y * L, dir=Y, label='Przesuń', min_px=36, color=(.2, .5, .9, 1)),
                               dict(id='vent:rot', start=P + X * L * 1.2, tip=P + X * L * 1.2 + Y * 6, dir=Y, label='Obróć', min_px=30, color=(.94, .6, .13, 1)),
                               dict(id='vent:size', start=P - X * L, tip=P - X * L * 1.6, dir=-X, label='Wielkość', min_px=30, color=(.18, .65, .43, 1)),
                               dict(id='vent:pitch', start=P - Y * L, tip=P - Y * L * 1.6, dir=-Y, label='Rozstaw', min_px=30, color=(.18, .65, .43, 1)),
                               dict(id='vent:depth', start=P, tip=P + N * L, dir=N, label='Głębokość', min_px=30, color=(.94, .6, .13, 1))])

    def vent_handle_dragged(self, hid, delta):
        """Przeciąganie: wartości w panelu idą za uchwytem, podgląd szybki (bez Boolean) do puszczenia."""
        a = self._vn_area()
        drag = self.vn.get('drag')
        if drag is None or drag['id'] != hid:
            drag = self.vn['drag'] = dict(id=hid, start=copy.deepcopy(a), cut=dict(self.vn['cut']))
        s0 = drag['start']
        d = float(delta)
        if hid == 'vent:x':
            a['ox'] = round(float(s0.get('ox', 0)) + d, 2)
        elif hid == 'vent:y':
            a['oy'] = round(float(s0.get('oy', 0)) + d, 2)
        elif hid == 'vent:rot':
            a['angle'] = round(float(s0.get('angle', 0)) + d * 9.0, 1)
        elif hid == 'vent:size':
            a['w'] = max(.2, round(float(s0.get('w', 4)) + d / 2, 2))
            a['h'] = max(.2, round(float(s0.get('h', 4)) + d / 2, 2))
        elif hid == 'vent:pitch':
            base = float(s0.get('px') or (float(s0.get('w', 4)) + float(s0.get('bridge', 1.2))))
            a['px'] = max(.5, round(base + d / 2, 2))
        elif hid == 'vent:depth':
            self.vn['cut']['depth'] = max(.05, round(float(drag['cut'].get('depth', 1.0)) + d / 4, 2))
        self._vn_sync_widgets()
        self.vn_level.blockSignals(True)
        self._vn_level_saved = self._vn_level_saved if getattr(self, '_vn_dragging', False) else self.vn_level.currentIndex()
        self._vn_dragging = True
        self.vn_level.setCurrentIndex(0)                                  # podczas przeciągania - szybki podgląd
        self.vn_level.blockSignals(False)
        self._vn_update()

    def vent_handle_released(self, hid):
        self.vn['drag'] = None
        if getattr(self, '_vn_dragging', False):
            self.vn_level.blockSignals(True)
            self.vn_level.setCurrentIndex(self._vn_level_saved)
            self.vn_level.blockSignals(False)
            self._vn_dragging = False
        self._vn_update()

    # ------------------------------------------------------------------ przyciski
    def vent_reset(self):
        a = self._vn_area()
        keep = {k: a[k] for k in ('region',) if k in a}
        self.vn['areas'][self.vn['cur']] = dict(copy.deepcopy(lib.preset(a.get('pattern_id') or 'circle')) or {}, **keep)
        self.vn['cut'] = dict(vf.CUT_DEFAULTS)
        self._vn_sync_widgets()
        self._vn_update()

    def vent_centre(self):
        a = self._vn_area()
        a.update(ox=0.0, oy=0.0, fill='E' if a.get('fill', 'A') in ('A', 'E') else a.get('fill'))
        self._vn_sync_widgets()
        self._vn_update()

    def _vn_config(self):
        return dict(area=copy.deepcopy(self._vn_area()), cut=dict(self.vn['cut']), multi=self.vn['multi'], mapping=self.vn['mapping'],
                    priority=self.vn['priority'], cross=self.vn['cross'])

    def _vn_apply_config(self, cfg):
        a = dict(vl.DEFAULTS, **(cfg.get('area') or {}))
        self.vn['areas'][self.vn['cur']] = a
        self.vn['cut'] = dict(vf.CUT_DEFAULTS, **(cfg.get('cut') or {}))
        for k_ in ('multi', 'mapping', 'priority', 'cross'):
            if cfg.get(k_):
                self.vn[k_] = cfg[k_]
        self._vn_sync_widgets()
        self._vn_update()

    def vent_save_template(self, name=None, category=None):
        if name is None:
            name, ok = QInputDialog.getText(self, 'Zapisz szablon wentylacji', 'Nazwa szablonu:')
            if not ok or not name.strip():
                return
            category, ok = QInputDialog.getText(self, 'Zapisz szablon wentylacji', 'Kategoria:', text='Moje')
            if not ok:
                category = 'Moje'
        lib.save_template(name.strip(), self._vn_config(), category or 'Moje')
        self._vn_lib_cache.pop('tpl:' + name.strip(), None)
        self._vn_library_fill()
        self.toast(f'Zapisano szablon „{name.strip()}”.')

    def vent_load_template(self):
        from .vent_templates_ui import TemplatesDialog
        dlg = TemplatesDialog(self, lambda cfg: self._vn_apply_config(cfg))
        dlg.exec()
        self._vn_lib_cache = {k: v for k, v in self._vn_lib_cache.items() if not k.startswith('tpl:')}
        self._vn_library_fill()

    def _step_fill_vent(self, recipe):
        self.vn.update(target=recipe['target'], faces=[dict(f) for f in recipe['faces']], areas=copy.deepcopy(recipe.get('areas') or [dict(vl.DEFAULTS)]),
                       cur=0, cut=dict(vf.CUT_DEFAULTS, **(recipe.get('cut') or {})), multi=recipe.get('multi', 'independent'),
                       cross=recipe.get('cross', 'stop'), mapping=recipe.get('mapping', 'auto'), priority=recipe.get('priority', 'shape'),
                       exclusions=copy.deepcopy(recipe.get('exclusions') or []), end_face=recipe.get('end_face'),
                       top=dict(density=recipe.get('density', 0.0), map_rotate=recipe.get('map_rotate', 0.0), allow_islands=recipe.get('allow_islands', False)))
        self._vn_sync_widgets()
        self._vn_update()

    def apply_vent(self):
        if self.busy or self.mode != 'vent' or not self.vn_apply.isEnabled():
            return
        recipe = self.vent_recipe()
        editing = (getattr(self, '_step_edit', None) or {}).get('recipe') or {}
        same = editing.get('type') == 'vent'
        recipe['id'] = editing.get('id') if same and editing.get('id') else uuid.uuid4().hex
        existing = list(self.document.bodies)
        gyro = (recipe['areas'][0].get('generator') or '') == 'gyroid3d'
        if gyro:
            recipe['type'] = 'vent'
            recipe['gyroid'] = True

        cache = getattr(self, '_vn_cache', None)
        pre = cache['value'] if cache and not gyro and cache['base'] == vf.signature(existing, recipe) else None   # wynik podglądu tego samego zadania

        def build_step():
            from .history import run_vent
            return run_vent(existing, recipe, pre)

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Wentylacja'
            self.document.pending_icon = 'vent'
            self.document.commit(bodies)

        def after():
            self.view.set_preview_mesh(None)
            self.view.set_handles([])
            self.vn.update(result=None, sel=set())
            self._vn_cache = self._vn_done = None

        self._vn_timer.stop()
        self.view.set_preview_mesh(None)
        self.run_operation('Wentylacja', build_step, apply, after=after)


# ---------------------------------------------------------------------------------------------- pomocnicze
def _outline_meshes(pl, only=None):
    """Obrysy otworów odwzorowane na ściany (szybki podgląd) - osobne siatki według stanu; strefy zabronione."""
    groups = {}
    for p_ in pl['plans']:
        ms, Ts = p_['mappers'], p_['T']
        for h in p_['holes']:
            if only is not None and (p_['area'], h['key']) not in only:
                continue
            st = 'sel' if only is not None else h.get('status', 'ok')
            poly = h['poly']
            if len(ms) > 1:
                m, _q = vf._locate(p_, h['c'])
                lm = vf._LocalMap(m, 0, Ts[ms.index(m)])
            else:
                lm = ms[0]
            try:
                pts = np.array([lm.to3d(q)[0] + lm.to3d(q)[1] * .02 for q in np.vstack([poly, poly[:1]])], np.float32)
            except kernel.CadError:
                continue
            groups.setdefault(st, []).append(pts)
        if only is None:
            for z in p_['zones']:
                try:
                    pts = np.array([ms[0].to3d(q)[0] for q in np.vstack([z['poly'], z['poly'][:1]])], np.float32)
                    groups.setdefault('zone', []).append(pts)
                except kernel.CadError:
                    pass
    out = {}
    for st, lines in groups.items():
        if len(lines) > 6000:
            lines = lines[:6000]
        allp = np.vstack(lines)
        out[st] = kernel.DisplayMesh(allp, np.empty((0, 3), np.uint32), {i: l for i, l in enumerate(lines)}, tuple(map(float, allp.mean(0))),
                                     float(np.ptp(allp, axis=0).max()) or 1.0)
    return out


def _parse_mixed(text):
    out = []
    for chunk in text.split(';'):
        t = chunk.split()
        if not t:
            continue
        kind = t[0]
        if kind not in vs.SHAPES:
            continue
        nums = [float(x.replace(',', '.')) for x in t[1:5] if _isnum(x)]
        out.append(dict(kind=kind, w=nums[0] if nums else 4.0, h=nums[1] if len(nums) > 1 else (nums[0] if nums else 4.0),
                        angle=nums[2] if len(nums) > 2 else 0.0, share=nums[3] if len(nums) > 3 else 1.0))
    return out


def _isnum(x):
    try:
        float(x.replace(',', '.'))
        return True
    except ValueError:
        return False


def _parse_gradients(text):
    out = []
    for chunk in text.split(';'):
        t = chunk.split()
        if not t:
            continue
        if len(t) < 5 or t[0] not in vl.GRAD_PARAMS or t[1] not in vl.GRAD_DIRS or t[2] not in vl.GRAD_FUNCS:
            raise ValueError(f'Gradient „{chunk.strip()}”: parametr kierunek funkcja od do (np. size h linear 1 0.5).')
        g = dict(param=t[0], dir=t[1], func=t[2], k0=float(t[3].replace(',', '.')), k1=float(t[4].replace(',', '.')))
        for extra in t[5:]:
            if ':' in extra and t[2] == 'custom':
                g['control'] = [[float(a), float(b)] for a, b in (pair.split(':') for pair in extra.split(','))]
            elif _isnum(extra):
                g['angle' if t[1] == 'diag' else 'steps'] = float(extra.replace(',', '.'))
        out.append(g)
    return out


def _format_gradients(gs):
    return '; '.join(f'{g["param"]} {g["dir"]} {g["func"]} {g.get("k0", 1):g} {g.get("k1", .5):g}' +
                     (' ' + ','.join(f'{a:g}:{b:g}' for a, b in g['control']) if g.get('control') else '') for g in gs)


def _check_custom(loops):
    """Kontrola konturów własnego wzoru: zamknięte, bez samoprzecięć, niezerowe."""
    from . import vent_geom2d as g2
    out = []
    for lp in loops:
        P = vs.sample_loop(lp, 64)
        if len(P) < 3 or abs(g2.area(P)) < 1e-6:
            continue
        if g2.self_intersects(P):
            raise kernel.CadError('Kontur własnego wzoru ma samoprzecięcie - popraw szkic.')
        out.append(lp)
    if not out:
        raise kernel.CadError('Brak poprawnych zamkniętych konturów.')
    out.sort(key=lambda lp: -abs(g2.area(vs.sample_loop(lp, 64))))
    return out


def import_pattern(path, tol=.05):
    """Wzór z pliku SVG / DXF → kontury własnego kształtu i raport. Krawędzie łączone w kontury (ShapeAnalysis_FreeBounds,
    tolerancja tol domyka drobne przerwy), duplikaty i fragmenty zerowej długości usuwane, kontury otwarte i z
    samoprzecięciem zgłaszane - na niepoprawnych konturach nie wycina się otworów."""
    from pathlib import Path
    from . import import2d
    from . import vent_geom2d as g2
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from OCP.TopTools import TopTools_HSequenceOfShape
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools_WireExplorer
    ext = Path(path).suffix.lower()
    sink = import2d.svg_edges(path) if ext == '.svg' else import2d.dxf_edges(path)
    edges = list(sink.edges)
    report = []
    seen, uniq, dup = [], [], 0
    for e in edges:                                                     # duplikaty (te same końce i środek)
        key = tuple(np.round(np.r_[e.startPoint().toTuple(), e.endPoint().toTuple(), e.positionAt(.5).toTuple()], 4))
        rkey = tuple(np.round(np.r_[e.endPoint().toTuple(), e.startPoint().toTuple(), e.positionAt(.5).toTuple()], 4))
        if key in seen or rkey in seen:
            dup += 1
            continue
        seen.append(key)
        uniq.append(e)
    if dup:
        report.append(('warning', f'Usunięto {dup} nakładających się krzywych.'))
    seq = TopTools_HSequenceOfShape()
    for e in uniq:
        seq.Append(e.wrapped)
    wires = TopTools_HSequenceOfShape()
    ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(seq, float(tol), False, wires)
    loops, opened, selfx = [], 0, 0
    for i in range(1, wires.Length() + 1):
        w = TopoDS.Wire_s(wires.Value(i))
        pts = []
        we = BRepTools_WireExplorer(w)
        while we.More():
            c = BRepAdaptor_Curve(we.Current())
            ts = np.linspace(c.FirstParameter(), c.LastParameter(), 2 if c.GetType() == 0 else 24)
            if we.Orientation() == 1:
                ts = ts[::-1]
            pts += [c.Value(float(t)).Coord()[:2] for t in ts[:-1]]
            last = c.Value(float(ts[-1])).Coord()[:2]
            we.Next()
        if len(pts) < 3:
            continue
        P = np.array(pts)
        if np.linalg.norm(P[0] - np.array(last)) > tol:
            opened += 1
            continue
        if g2.self_intersects(P):
            selfx += 1
            continue
        loops.append([('L', P[k], P[(k + 1) % len(P)]) for k in range(len(P))])
    if opened:
        report.append(('warning', f'{opened} otwartych konturów pominięto (przerwa > {tol:g} mm).'))
    if selfx:
        report.append(('warning', f'{selfx} konturów z samoprzecięciem pominięto.'))
    if not loops:
        raise kernel.CadError('Plik nie zawiera poprawnych zamkniętych konturów - nie można użyć go jako wzoru.')
    report.insert(0, ('ok', f'Wczytano {len(loops)} kontur(y) z pliku.'))
    return _check_custom(loops), report

