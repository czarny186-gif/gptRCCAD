"""Okno „Studio”: układ, grafika i sposób modelowania / szkicowania odtworzone z wersji HTML (natywnie, bez przeglądarki)."""
from __future__ import annotations
import json
import math
import uuid
import cadquery as cq
from dataclasses import replace
from pathlib import Path
import numpy as np
from PySide6.QtCore import QEvent, QObject, QPoint, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QCursor, QFont, QFontDatabase, QIcon, QKeySequence, QMatrix4x4, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFontComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget)
from .objects import ObjectsPanel, category
from . import kernel
from . import shell_ui as ui
from . import snap as snapping
icons_green = '#2fa56d'
icons_orange = '#f09a22'
from .perfcache import LRU
from .spatial import BoundsTree

from .document import Body, Document
from . import history as hist
from . import workers
from functools import partial
from . import sheetmetal as shm
from . import sheetedit as she
from .viewcube import ViewCube
from . import sketchmeta as sm
from . import settings
from .viewport import CadView, VIEWS as VIEWS_FOR_CUBE, pan_arrow
from .plywood_ui import PlywoodTools, PLY_MODES
from .scale_ui import ScaleTools
from .sectionview import SectionTools
from PySide6.QtWidgets import QSizePolicy
from . import measurement
from html import escape as html_escape

NEED = {'rect': 2, 'centerRect': 2, 'rect3': 3, 'circle': 2, 'circle2': 2, 'circle3': 3, 'ellipse': 2, 'slot': 3, 'polygon': 2,
        'arc': 3, 'point': 1, 'construction': 2, 'measure': 2, 'text': 1, 'trim': 1, 'offset': 1, 'line': 2, 'circleTangent2': 3}
HINTS = {
    'rect': ['Kliknij pierwszy narożnik prostokąta.', 'Kliknij przeciwległy narożnik.'],
    'centerRect': ['Kliknij środek prostokąta.', 'Kliknij narożnik.'],
    'rect3': ['Kliknij pierwszy punkt podstawy.', 'Kliknij drugi punkt podstawy.', 'Kliknij punkt określający wysokość.'],
    'circle': ['Kliknij środek okręgu.', 'Kliknij punkt na okręgu (promień).'],
    'circle2': ['Kliknij pierwszy koniec średnicy.', 'Kliknij drugi koniec średnicy.'],
    'circle3': ['Kliknij pierwszy punkt okręgu.', 'Kliknij drugi punkt.', 'Kliknij trzeci punkt.'],
    'circleTangent2': ['Kliknij pierwszą linię.', 'Kliknij drugą linię.', 'Kliknij, aby wskazać wielkość okręgu.'],
    'ellipse': ['Kliknij środek elipsy.', 'Kliknij narożnik opisanego prostokąta.'],
    'slot': ['Kliknij środek pierwszego końca.', 'Kliknij środek drugiego końca.', 'Kliknij punkt określający szerokość.'],
    'polygon': ['Kliknij środek wielokąta (liczbę kątów ustawisz strzałką przy wielokącie na pasku).',
                'Wierzchołek idzie za kursorem (także przyciągniętym do kratki / punktu): odległość - wielkość, kierunek - obrót · klik zatwierdza · Tab - wymiary'],
    'arc': ['Kliknij początek łuku.', 'Kliknij punkt na łuku.', 'Kliknij koniec łuku.'],
    'point': ['Kliknij miejsce punktu.'],
    'construction': ['Kliknij początek linii konstrukcyjnej.', 'Kliknij koniec.'],
    'measure': ['Kliknij pierwszy punkt pomiaru.', 'Kliknij drugi punkt.'],
    'text': ['Wybierz powierzchnię, przeciągnij obszar napisu i wpisz treść.'],
    'trim': ['Nożyczki: kliknij fragment szkicu, który ma zniknąć.'],
    'offset': ['Ofset: kliknij kształt szkicu, który chcesz odsunąć.'],
    'line': ['Kliknij początek linii.', 'Kliknij kolejny punkt. Enter lub ponowne kliknięcie kończy, kliknięcie w pierwszy punkt zamyka obrys.'],
}
VARIANT_LABELS = {'rect': '2 narożniki', 'centerRect': 'Od środka', 'rect3': '3 punkty', 'circle': 'Środek + promień',
                  'circleTangent2': 'Styczny do 2 elementów', 'circle2': 'Od 2 punktów', 'circle3': 'Od 3 punktów'}
DIM_LABELS = {'rect': ('Szerokość (mm)', 'Wysokość (mm)'), 'centerRect': ('Szerokość (mm)', 'Wysokość (mm)'), 'ellipse': ('Szerokość (mm)', 'Wysokość (mm)'),
              'circle': ('Promień (mm)',), 'polygon': ('Promień (mm)', 'Obrót (°)'), 'circle2': ('Średnica (mm)',),
              'line': ('Długość (mm)', 'Kąt (°)'), 'construction': ('Długość (mm)', 'Kąt (°)'), 'measure': ('Długość (mm)', 'Kąt (°)')}
HEM_DEFAULT = dict(radius=2.0, length=10.0, gap=0.1)     # Zawinięcie: wartości przycisku Reset
FLANGE_DEFAULT = dict(radius=0.5, angle=90.0, length=5.0, measure='outer')     # Kołnierz: wartości przycisku Reset
RULES_DEFAULT = dict(gap=0.1, relief='none', relief_size=3.0, joint='sheet')     # Reguły blach: wartości przycisku Reset
AXES = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
AXIS_COLORS = ((.89, .31, .33, 1), (.14, .64, .42, 1), (.2, .5, .9, 1))
TINT_BASE = (.30, .55, .95, 1)
TINT_TOOL = (.95, .55, .20, 1)
PREVIEW_BLUE = (.30, .62, .91, .73)
PREVIEW_TOL = .3
SKETCH_ORANGE = (.95, .55, .1, 1)
MOD_PREVIEW = (.66, .45, .90, .80)          # tworzone zaokrąglenie / faza: ciepły fiolet
MOD_PREVIEW_LINE = (.45, .22, .72, 1)


def fmt(value, digits=3):
    return f'{value:.{digits}f}'.replace('.', ',')


def kernel_close(a, b, tol=1e-3):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


_CENTERS = {}


def _center(shape):
    """Środek masy bryły (cq Vector) zapamiętany dla kształtu - liczenie go przy każdej zmianie wartości zacinało okno."""
    hit = _CENTERS.get(id(shape))
    if hit is None or hit[0] is not shape:
        if len(_CENTERS) > 256:
            _CENTERS.clear()
        hit = _CENTERS[id(shape)] = (shape, shape.Center())
    return hit[1]


def _merge_meshes(meshes):
    """Łączy kilka siatek podglądu w jedną."""
    if len(meshes) == 1:
        return meshes[0]
    vertices, triangles, edges, offset, key = [], [], {}, 0, 0
    for m in meshes:
        vertices.append(m.vertices)
        triangles.append(m.triangles + offset)
        offset += len(m.vertices)
        for points in m.edges.values():
            edges[key] = points
            key += 1
    return kernel.DisplayMesh(np.vstack(vertices), np.vstack(triangles), edges, meshes[0].center, meshes[0].size)


def _fit_circle(points):
    """(promień, środek) okręgu dopasowanego do łamanej w przestrzeni albo (None, None), gdy punkty nie leżą na okręgu."""
    pts = np.asarray(points, float)
    if len(pts) < 4:
        return None, None
    mean = pts.mean(axis=0)
    _, sing, vt = np.linalg.svd(pts - mean)
    if sing[1] < 1e-6 * max(sing[0], 1.0):
        return None, None
    u, v = vt[0], vt[1]
    xy = np.column_stack([(pts - mean) @ u, (pts - mean) @ v])
    a = np.column_stack([2 * xy, np.ones(len(xy))])
    sol, *_ = np.linalg.lstsq(a, (xy ** 2).sum(axis=1), rcond=None)
    radius = float(np.sqrt(max(sol[2] + sol[0] ** 2 + sol[1] ** 2, 0.0)))
    if radius < 1e-9 or float(np.max(np.abs(np.linalg.norm(xy - sol[:2], axis=1) - radius))) > 0.01 * radius + 1e-6:
        return None, None
    return radius, mean + u * sol[0] + v * sol[1]


def profile_face(wire):
    """Powierzchnia ograniczona zamkniętym drutem (do podświetlania profilu)."""
    import cadquery as cq
    try:
        return cq.Face.makeFromWires(wire)
    except Exception:
        return None


class _ExprBox(QLineEdit):
    """Pole liczby albo wyrażenia (np. szerokość / 2). raw() zwraca liczbę albo {'expr': tekst}; value() - policzoną liczbę."""

    def __init__(self, value=0.0, values=None):
        super().__init__()
        self.values = values or {}
        self.setValue(value)

    def setValue(self, value):
        self.setText(value['expr'] if isinstance(value, dict) else f'{float(value):g}')

    def raw(self):
        text = self.text().strip()
        try:
            return float(text.replace(',', '.'))
        except ValueError:
            return {'expr': text}

    def value(self):
        raw = self.raw()
        return hist.evaluate(raw['expr'], self.values) if isinstance(raw, dict) else raw


class _HistChip(QToolButton):
    """Symbol kroku historii: klik = przeskok, dwuklik = edycja parametrów kroku."""
    editRequested = Signal()

    def mouseDoubleClickEvent(self, event):
        self.editRequested.emit()


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Work(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = _Signals()

    def run(self):
        try:
            value = self.function()
        except Exception as exc:
            message = str(exc) if isinstance(exc, kernel.CadError) else f'Operacja nie powiodła się: {exc}'
            try:
                self.signals.failed.emit(message)
            except RuntimeError:
                pass        # okno zamknięte, zanim praca w tle się skończyła (np. przygotowanie rozwinięcia)
            return
        try:
            self.signals.done.emit(value)
        except RuntimeError:
            pass


def _spin(value, low=-1e6, high=1e6, decimals=3, step=1.0):
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    box.setButtonSymbols(QDoubleSpinBox.NoButtons)
    return box


def _label(text, name='label'):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


# zakładki paska narzędzi: nazwa -> narzędzia w kolejności (nowe funkcje dopisujemy do pasującej zakładki)
TABS = {'Ulubione': ['toolbox'], 'Szkic': ['sketch', 'surface'], 'Bryła': ['extrude', 'revolve', 'sweep', 'loft'], 'Edycja': ['mod', 'shell', 'thread', 'bool', 'split', 'mate', 'align'], 'Blacha': ['sheet', 'flange', 'hem', 'tabwall', 'rules', 'unfold_sheet', 'fold_sheet', 'flat'],
        'Sklejka': ['ply', 'ply_wall', 'ply_between', 'ply_joints', 'ply_cut', 'ply_unfold', 'ply_fold'],
        'Wzory': ['mirror', 'pattern'], 'Pomiary': ['mdist', 'mangle', 'mrad', 'mprops'], 'Rysunek': ['drawing', 'autodrawing', 'sheetdrawing', 'plydrawing', 'importdrawing'],
        'Biblioteka': ['libimport', 'libobj', 'libsketch']}
TAB_OF = {tool: tab for tab, tools in TABS.items() for tool in tools}
# narzędzia, które można dodać do Ulubionych (bez Pliku, Przybornika i przycisku „Inna powierzchnia”, widocznego tylko w szkicu)
FAVORITE_TOOLS = [tool for tab, tools in TABS.items() if tab != 'Ulubione' for tool in tools if tool != 'surface']
TAB_TOP = 14        # pasek zakładek
TOOLS_TOP = 50      # przyciski narzędzi pod zakładkami
MEASURE_MODES = ('mdist', 'mangle', 'mrad', 'mprops')
DRAWING_MODES = ('drawing', 'autodrawing', 'sheetdrawing', 'plydrawing')


class StudioWindow(SectionTools, ScaleTools, PlywoodTools, QMainWindow):
    def __init__(self):
        super().__init__()
        self.document = Document()
        self.pool = QThreadPool.globalInstance()
        self.warm_pool = QThreadPool(self)            # osobny wątek na rozwinięcia liczone w tle (nie blokuje operacji)
        self.warm_pool.setMaxThreadCount(1)
        from . import workers
        QTimer.singleShot(1500, workers.start)        # procesy liczące startują w tle, gdy okno jest już widoczne
        self._warming = set()
        self._refining = set()
        self._refine_timer = QTimer(self)
        self._refine_timer.setSingleShot(True)
        self._refine_timer.setInterval(60)
        self._refine_timer.timeout.connect(lambda: self._refine_meshes())
        self._warm_timer = QTimer(self)
        self._warm_timer.setSingleShot(True)
        self._warm_timer.setInterval(400)
        self._warm_timer.timeout.connect(lambda: self._warm_sheets())
        self.busy = False
        self._cancel_op = None
        self.selected: list[str] = []
        self.hidden_ids: set[str] = set()
        self.revealed_ids: set[str] = set()      # szkice wygaszone po wyciągnięciu, pokazane okiem na liście
        self.locked_ids: set[str] = set()
        self._obj_no: dict[str, int] = {}
        self._obj_count: dict[str, int] = {}
        self._obj_doc = None
        self._obj_hover = ''
        self.edges: dict[str, set] = {}
        self.mode = None            # None | plane | sketch | extrude | bool | mod | mirror | move | rotate
        self.tool = 'rect'
        self.sides = 5
        self.points: list[tuple[float, float]] = []
        self.last_uv = (0.0, 0.0)
        self.sketch_plane = None
        self.tangent_lines = []
        self.ex_profiles: list[dict] = []
        self.rev_profiles: list[dict] = []
        self.rev_line = None
        self._rev_manual = False
        self.sh_id = None
        self.sh_faces: list[dict] = []
        self.ms_points: list = []
        self._tab = 'Szkic'
        self.sw_profiles: list[dict] = []
        self.sw_path = None
        self.lf_profiles: list[dict] = []
        self.lf_point = None
        self._hv = None
        self.bool_ids: list[str] = []
        self.mirror_id = None
        self.mirror_frame = None
        self.override: dict[str, Body] = {}
        self.t_target = None
        self.t_center = np.zeros(3)
        self.t_mass = np.zeros(3)
        self.t_radius = 10.0
        self.clipboard: list[tuple] = []
        self._result_preview = False
        self._hover_key = None
        self._work = None
        self._popup = None
        self._planes_visible = True
        self._pv = {}
        self._region_cache = {}
        self._trim_cache = None
        self._snap_cache = None
        self.resize(1400, 850)
        self.setStyleSheet(ui.style())
        self.view = CadView(self)
        self.view.click_mode = True
        self.setCentralWidget(self.view)
        self.view.sketchMoved.connect(self.sketch_moved)
        self.view.sketchClicked.connect(self.sketch_clicked)
        self.view.viewClicked.connect(self.view_clicked)
        self.view.viewHover.connect(self.view_hover)
        self.view.viewDoubleClicked.connect(self.view_double_clicked)
        self._mod_face_mesh = None
        self.mod_vertices = {}
        self.view.contextRequested.connect(self.context_menu)
        self.view.handleDragged.connect(self.handle_dragged)
        self.view.handleReleased.connect(self.handle_released)
        self.view.pointDragged.connect(self.handle_point_dragged)
        self._build_overlays()
        self.view.installEventFilter(self)
        QApplication.instance().installEventFilter(self)
        self._timers = {}
        for name, slot in (('extrude', self.update_extrude_preview), ('revolve', self.update_revolve_preview), ('shell', self.update_shell_preview), ('sweep', self.update_sweep_preview), ('loft', self.update_loft_preview), ('mod', self.update_mod_preview), ('bool', self.update_bool_preview),
                           ('mirror', self.update_mirror_preview), ('split', self.update_split_preview), ('pattern', self.update_pattern_preview), ('transform', self.update_transform_preview), ('dim', self.update_dim_preview),
                           ('gizmo', self._place_gizmo), ('ply_joints', self.update_ply_joints_preview)):
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(16 if name in ('extrude', 'mod') else (300 if name == 'ply_joints' else 40))
            timer.timeout.connect(slot)
            self._timers[name] = timer
        for seq, fn in (('Ctrl+Z', self.undo), ('Ctrl+Y', self.redo), ('Ctrl+Shift+Z', self.redo), ('Ctrl+S', self.save_project),
                        ('Ctrl+O', self.open_project), ('Ctrl+N', self.new_project), ('Delete', self.delete_selected),
                        ('Ctrl+C', self.copy_selected), ('Ctrl+X', self.cut_selected), ('Ctrl+V', self.paste_clipboard)):
            QShortcut(QKeySequence(seq), self, activated=fn)
        self.refresh(True)
        self.view.show_planes(True)
        self._layout_overlays()
        self.set_origin_text()

    # =====================================================================
    # budowa interfejsu (wymiary i kolory z CSS wersji HTML)
    # =====================================================================
    def _panel(self, width, title, kind='sketch', subtitle='', color=None, plain=False, scroll=False):
        """Panel opcji. scroll=True: treść przewija się, a przyciski dodane do frame.footer stoją zawsze na dole, widoczne
        także na niskim ekranie (wysokość panelu dopasowuje _fit_panel do miejsca nad paskiem historii)."""
        frame = QFrame(self.view)
        frame.setObjectName('panel')
        frame.setFixedWidth(width)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 15, 16, 15)
        lay.setSpacing(11)
        lay.addWidget(ui.panel_header(kind, title, subtitle, color or ui.icons.BLUE, plain))
        ui.shadow(frame, 26, 7, 46)
        frame.hide()
        frame.scroll = None
        if scroll:
            frame.setFixedWidth(width + 12)          # miejsce na pasek przewijania, pola zachowują dotychczasową szerokość
            lay.setContentsMargins(16, 15, 8, 15)
            area = QScrollArea()
            area.setObjectName('panelscroll')
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            area.setStyleSheet('QScrollArea#panelscroll, QWidget#panelbody { background: transparent; }'
                               'QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }'
                               'QScrollBar::handle:vertical { background: #c3d2e1; border-radius: 4px; min-height: 28px; }'
                               'QScrollBar::handle:vertical:hover { background: #9fb4c8; }'
                               'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }'
                               'QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }')
            body = QWidget()
            body.setObjectName('panelbody')
            # treść zawsze na szerokość panelu (szersze czcionki, np. w Windows, nie wypychają pól poza prawą krawędź)
            from PySide6.QtWidgets import QSizePolicy
            body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            inner = QVBoxLayout(body)
            inner.setContentsMargins(0, 0, 12, 0)
            inner.setSpacing(11)
            area.setWidget(body)
            area.viewport().setAutoFillBackground(False)
            lay.addWidget(area, 1)
            footer = QVBoxLayout()
            footer.setContentsMargins(0, 0, 12, 0)
            footer.setSpacing(8)
            lay.addLayout(footer)
            frame.scroll, frame.footer = (area, body), footer
            return frame, inner
        return frame, lay

    def _fit_panel(self, frame, top):
        """Panel z przewijaną treścią: wysokość tylko taka, jak trzeba, ale nie niżej niż do paska historii (przyciski zawsze widoczne)."""
        if getattr(frame, 'scroll', None) is None:
            frame.adjustSize()
            return
        area, body = frame.scroll
        H = self.view.height()
        bottom = self.hist_bar.y() - 12 if self.hist_bar.isVisible() and self.hist_bar.y() > top else H - 18
        natural = getattr(frame,'_measure_body_height',None)
        if natural is None:natural=body.sizeHint().height()
        frame.layout().activate()
        frame.adjustSize()
        other = frame.height() - area.height()        # nagłówek, stopka z przyciskami i marginesy (rzeczywiste wymiary)
        area.setFixedHeight(int(max(90, min(natural, bottom - top - other))))
        frame.adjustSize()

    @staticmethod
    def _field(layout, text, widget):
        layout.addWidget(_label(text))
        layout.addWidget(widget)
        return widget

    @staticmethod
    def _buttons(layout, first, second, on_first, on_second):
        row = QHBoxLayout()
        row.setSpacing(6)
        a, b = QPushButton(first), QPushButton(second)
        a.setObjectName('primary')
        a.clicked.connect(lambda _=False: on_first())
        b.clicked.connect(lambda _=False: on_second())
        row.addWidget(a)
        row.addWidget(b)
        layout.addLayout(row)
        return a, b

    @staticmethod
    def _pic_field(lay, text, kind, widget, tip, size=48):
        """Pole z obrazkiem: podpis, a pod nim obrazek ustawienia i pole do wpisania obok."""
        lay.addWidget(_label(text))
        row = QHBoxLayout()
        row.setSpacing(12)
        pic = QLabel()
        pic.setFixedSize(size, size)
        pic.setPixmap(ui.icons.pixmap(kind, size))
        pic.setToolTip(tip)
        row.addWidget(pic)
        row.addWidget(widget, 1)
        lay.addLayout(row)
        return pic

    def _bend_buttons(self, footer, prefix, on_save, on_reset, save_tip, reset_tip):
        """Przyciski Kołnierza / Zawinięcia: Zatwierdź, Zaginaj (czerwony = wyginanie włączone), Reset, Zamknij."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        save, bend, reset, close = QPushButton('Zatwierdź'), QPushButton('Zaginaj'), QPushButton('Reset'), QPushButton('Zamknij')
        save.setObjectName('primary')
        save.setToolTip(save_tip)
        bend.setToolTip('Czerwony: wyginanie włączone - kliknięcie krawędzi blachy dodaje gięcie. Zielony: wyłączone.')
        reset.setToolTip(reset_tip)
        save.clicked.connect(lambda _=False: on_save())
        bend.clicked.connect(lambda _=False: self.toggle_bending())
        reset.clicked.connect(lambda _=False: on_reset())
        close.clicked.connect(lambda _=False: self.set_mode(None))
        for i, b in enumerate((save, bend, reset, close)):
            grid.addWidget(b, i // 2, i % 2)
        footer.addLayout(grid)
        for name, b in zip(('save', 'bend', 'reset', 'close'), (save, bend, reset, close)):
            setattr(self, f'{prefix}_{name}', b)

    @staticmethod
    def _buttons3(layout, on_confirm, on_cancel, on_close):
        """Trzy przyciski panelu: Zatwierdź (ustawienia i dodawanie kliknięciem), Anuluj, Zamknij."""
        row = QHBoxLayout()
        row.setSpacing(6)
        for text, fn in (('Zatwierdź', on_confirm), ('Anuluj', on_cancel), ('Zamknij', on_close)):
            b = QPushButton(text)
            if text == 'Zatwierdź':
                b.setObjectName('primary')
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        layout.addLayout(row)

    def _build_overlays(self):
        v = self.view
        icons = [('file', ui.style_icon('file', 38), 'Plik'),
                 ('toolbox', ui.style_icon('toolbox', 38), 'Przybornik — wybierz ulubione narzędzia do zakładki Ulubione'),
                 ('sketch', ui.style_icon('sketch', 38), 'Nowy szkic'),
                 ('extrude', ui.style_icon('extrude', 38), 'Wyciągnij'),
                 ('revolve', ui.style_icon('revolve', 38), 'Obrót — profil wokół osi'),
                 ('sweep', ui.style_icon('sweep', 38), 'Przeciągnięcie — profil wzdłuż ścieżki'),
                 ('loft', ui.style_icon('loft', 38), 'Wyciągnięcie złożone — bryła przez kilka profili'),
                 ('mate', ui.style_icon('mate', 38), 'Dopasowanie — ściana jednej bryły przylega do ściany drugiej, środkami ścian'),
                 ('align', ui.style_icon('align', 38), 'Wyrównanie — ściana jednej bryły na tej samej wysokości co ściana drugiej'),
                 ('surface', ui.style_icon('surface', 38), 'Inna powierzchnia — wskaż inną ścianę bryły albo płaszczyznę do rysowania'),
                 ('bool', ui.style_icon('bool', 38), 'Boolean / CSG'),
                 ('mod', ui.style_icon('mod', 38), 'Edytuj bryłę — zaokrąglenie i fazowanie'),
                 ('split', ui.style_icon('split', 38), 'Przetnij bryłę — płaszczyzną, ścianą, szkicem albo inną bryłą'),
                 ('shell', ui.style_icon('shell', 38), 'Skorupa — wydrąż bryłę i otwórz ściany'),
                 ('thread', ui.style_icon('thread', 38), 'Gwint — gwint wewnętrzny lub zewnętrzny na otworze albo wałku'),
                 ('sheet', ui.style_icon('sheet', 38), 'Konwertuj na blachę — wybierz płaski prostokąt prostopadłościanu'),
                 ('flange', ui.style_icon('flange', 38), 'Kołnierz — wybierz krawędź blachy'),
                 ('hem', ui.style_icon('hem', 38), 'Zawinięcie — zawiń krawędź blachy o 180°, z przerwą albo zaciśnięte'),
                 ('tabwall', ui.style_icon('tabwall', 38), 'Kołnierz na noski — ścianka bez gięcia, połączona noskami z blachą (wymiary jak przy kołnierzu)'),
                 ('rules', ui.style_icon('rules', 38), 'Reguły blach — szczelina i wycięcia w narożnikach'),
                 ('unfold_sheet', ui.style_icon('unfold_sheet',38), 'Rozłóż blachę — edytuj płaskie rozwinięcie'),
                 ('fold_sheet', ui.style_icon('fold_sheet',38), 'Zegnij blachę — przywróć gięcia z wykonanymi zmianami'),
                 ('flat', ui.style_icon('flat', 38), 'Rozwinięcie DXF — zaznacz jedną blachę w drzewie obiektów'),
                 ('ply', ui.style_icon('ply', 38), 'Płyta — szkic albo ściana jako płyta ze sklejki (laser, frezarka, druk 3D)'),
                 ('ply_wall', ui.style_icon('ply_wall', 38), 'Ścianka — płyta na krawędzi płyty, jak przy blasze'),
                 ('ply_between', ui.style_icon('ply_between', 38), 'Półka / przegroda — płyta między dwiema ścianami'),
                 ('ply_joints', ui.style_icon('ply_joints', 38), 'Połączenia — wczepy, czopy, rowki i nacięcia tam, gdzie płyty się stykają'),
                 ('ply_cut', ui.style_icon('ply_cut', 38), 'Do cięcia — lista płyt i plik DXF / STL do lasera, frezarki, drukarki'),
                 ('ply_unfold', ui.style_icon('ply_unfold', 38), 'Rozłóż płyty — pudełko / mebel ze sklejki płasko, płyta obok płyty'),
                 ('ply_fold', ui.style_icon('ply_fold', 38), 'Złóż płyty — rozłożone płyty z powrotem w pudełko / mebel'),
                 ('mirror', ui.style_icon('mirror', 38), 'Odbicie lustrzane'),
                 ('pattern', ui.style_icon('pattern', 38), 'Szyk — prostokątny, kołowy, wzdłuż linii'),
                 ('mdist', ui.style_icon('mdist', 38), 'Pomiar odległości między dwoma punktami'),
                 ('mangle', ui.style_icon('mangle', 38), 'Pomiar kąta (trzy punkty)'),
                 ('mrad', ui.style_icon('mrad', 38), 'Promień, średnica i długość krawędzi'),
                 ('mprops', ui.style_icon('mprops', 38), 'Właściwości: objętość, pole, wymiary, środek masy'),
                 ('drawing', ui.style_icon('drawing', 38), 'Utwórz rysunek techniczny — rzuty, wymiary, pomiary, zapis'),
                 ('autodrawing', ui.style_icon('autodrawing', 38), 'Rysunek automatyczny — rzuty i opisy same, zapis do pliku'),
                 ('sheetdrawing', ui.style_icon('sheetdrawing', 38), 'Rysunek blachy do gięcia — rozwinięcie z liniami gięcia, wymiarami, promieniem i grubością'),
                 ('plydrawing', ui.style_icon('plydrawing', 38), 'Rysunek płyt — pudełko / mebel ze sklejki rozłożony na wszystkie płyty z wymiarami'),
                 ('importdrawing', ui.style_icon('importdrawing', 38), 'Załaduj plik — rysunek techniczny z pliku SVG albo DXF z komputera'),
                 ('libimport', ui.style_icon('libimport', 38), 'Importuj — model STEP, STL, BREP albo szkic DXF, SVG na pole robocze'),
                 ('libobj', ui.style_icon('libobj', 38), 'Wstaw obiekt — biblioteka obiektów: foldery, import, eksport, wstawianie'),
                 ('libsketch', ui.style_icon('libsketch', 38), 'Wstaw szkic — biblioteka szkiców: foldery, import DXF / SVG, wstawianie')]
        self.tools = {}
        for key, icon, tip in icons:
            button = ui.big_tool(icon, tip, checkable=key not in ('file', 'surface', 'importdrawing', 'toolbox', 'libimport', 'libobj', 'libsketch'))
            button.setParent(v)
            ui.shadow(button, 12, 3, 36)
            self.tools[key] = button
            if key in ('unfold_sheet', 'fold_sheet', 'flat'):
                button.clicked.connect(lambda _=False, k=key: self.sheet_command(k))
            elif key in ('ply_unfold', 'ply_fold'):
                button.clicked.connect(lambda _=False, k=key: self.ply_fold_command(k))
            elif key == 'importdrawing':
                button.clicked.connect(lambda _=False: self.import_drawing_file())
            elif key == 'surface':
                button.clicked.connect(lambda _=False: self.pick_other_surface())
            elif key == 'toolbox':
                button.clicked.connect(lambda _=False: self.open_toolbox())
            elif key == 'libimport':
                button.clicked.connect(lambda _=False: self.import_model())
            elif key in ('libobj', 'libsketch'):
                button.clicked.connect(lambda _=False, k=key: self.open_library('object' if k == 'libobj' else 'sketch'))
            elif key != 'file':
                button.clicked.connect(lambda _=False, k=key: self.toggle_mode(k))
        self.tools['file'].clicked.connect(self.file_menu)
        self.favorites = self._load_favorites()
        self.tab_buttons = {}
        for name in TABS:
            tab = QToolButton(v)
            tab.setObjectName('tab')
            tab.setText(name)
            tab.setCheckable(True)
            tab.setAutoExclusive(True)
            tab.setCursor(Qt.PointingHandCursor)
            tab.setToolTip('Zakładka narzędzi: ' + ', '.join(self._tool_name(k) for k in self._tab_tools(name)))
            tab.clicked.connect(lambda _=False, n=name: self.set_tab(n))
            self.tab_buttons[name] = tab
        self.tab_buttons[self._tab].setChecked(True)

        self._build_shape_bar()

        undo_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><path d="M11 8L5 14l6 6" fill="none" stroke="currentColor" stroke-width="2.6" '
                    'stroke-linecap="round" stroke-linejoin="round"/><path d="M5 14h13a7 7 0 0 1 0 14h-4" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg>')
        redo_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><path d="M21 8l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.6" '
                    'stroke-linecap="round" stroke-linejoin="round"/><path d="M27 14H14a7 7 0 0 0 0 14h4" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg>')
        self.clear_button = self._round(ui.style_icon('trash', 24), 'Wyczyść całe pole', self.clear_all)
        self.undo_button = self._round(ui.style_icon('undo', 24), 'Cofnij (Ctrl+Z)', self.undo)
        self.redo_button = self._round(ui.style_icon('redo', 24), 'Ponów (Ctrl+Y)', self.redo)
        self.section_button=QToolButton(v)
        self.section_button.setObjectName('layers');self.section_button.setCheckable(True)
        self.section_button.setFixedSize(40,40);self.section_button.setIcon(ui.style_icon('section',26));self.section_button.setIconSize(QSize(26,26))
        self.section_button.setToolTip('Widok przekroju — wybierz ścianę, przeciągnij strzałkę i pracuj wewnątrz modelu')
        self.section_button.clicked.connect(self.toggle_section)
        ui.shadow(self.section_button,12,3,28)
        self.scale_button = QToolButton(v)
        self.scale_button.setObjectName('layers')
        self.scale_button.setCheckable(True)
        self.scale_button.setFixedSize(40, 40)
        self.scale_button.setIcon(ui.style_icon('scale', 26))
        self.scale_button.setIconSize(QSize(26, 26))
        self.scale_button.setToolTip('Skalowanie — zmień rozmiar zaznaczonych obiektów, szkiców albo całej grupy')
        self.scale_button.clicked.connect(lambda _=False: self.toggle_scale(self.scale_button.isChecked()))
        ui.shadow(self.scale_button, 12, 3, 28)
        self.layers = QToolButton(v)
        self.layers.setObjectName('layers')
        self.layers.setCheckable(True)
        self.layers.setChecked(True)
        self.layers.setFixedSize(40, 40)
        self.layers.setIcon(ui.style_icon('layers', 26))
        self.layers.setIconSize(QSize(26, 26))
        self.layers.setToolTip('Pokaż / ukryj płaszczyzny')
        self.layers.toggled.connect(self._planes_toggled)
        ui.shadow(self.layers, 12, 3, 28)
        self.xray = QToolButton(v)
        self.xray.setObjectName('layers')
        self.xray.setCheckable(True)
        self.xray.setFixedSize(40, 40)
        xicon = QIcon()
        xicon.addPixmap(ui.icons.pixmap('xray', 26), QIcon.Normal, QIcon.Off)
        xicon.addPixmap(ui.icons.pixmap('xray_w', 26), QIcon.Normal, QIcon.On)
        xicon.addPixmap(ui.icons.pixmap('xray_w', 26), QIcon.Active, QIcon.On)
        self.xray.setIcon(xicon)
        self.xray.setIconSize(QSize(26, 26))
        self.xray.setToolTip('Przezroczyste bryły (podgląd ukrytych krawędzi)')
        self.xray.toggled.connect(self._xray_toggled)
        ui.shadow(self.xray, 12, 3, 28)
        self.home = QToolButton(v)
        self.home.setObjectName('home')
        self.home.setIcon(ui.style_icon('home', 24))
        self.home.setIconSize(QSize(24, 24))
        self.home.setFixedSize(36, 36)
        self.home.setToolTip('Widok domowy')
        self.home.clicked.connect(lambda: (self.view.set_view('iso'), self.view.fit_all(), self._mark_view('iso')))
        ui.shadow(self.home, 12, 3, 28)

        # kostka orientacji (jak ViewCube w Fusion 360): obraca się z kamerą, ściana / narożnik = widok
        self.cube = ViewCube(self.view, v)
        self.busy_bar = ui.BusyBar(v, self.working)      # pasek pod kostką: coś liczy się w tle
        self.objects = ObjectsPanel(v)
        self.objects.select.connect(self.objects_select)
        self.objects.hide_toggled.connect(self.objects_hide)
        self.objects.lock_toggled.connect(self.objects_lock)
        self.objects.delete_requested.connect(self.objects_delete)
        self.objects.group_hide.connect(self.objects_group_hide)
        self.objects.group_delete.connect(self.objects_group_delete)
        self.objects.rename.connect(self.objects_rename)
        self.objects.hover.connect(self.objects_hover)
        self.objects.folder_move.connect(self.objects_folder_move)
        self.objects.folder_new.connect(self.objects_folder_new)
        self.objects.folder_rename.connect(self.objects_folder_rename)
        self.objects.folder_hide.connect(self.objects_folder_hide)
        self.objects.folder_delete.connect(self.objects_folder_delete)
        self.objects.folder_select.connect(self.objects_folder_select)
        ui.shadow(self.cube, 22, 5, 32)
        self.cube_buttons = {}
        self.cube.faceClicked.connect(self._cube_clicked)
        self.cube.directionClicked.connect(lambda az, el: (self.view.setCameraPosition(azimuth=az, elevation=el), self.view.update()))
        self.cube.rotateClicked.connect(self._cube_rotate)
        self.cube.rollClicked.connect(self._cube_roll)
        self.view.cameraMoved.connect(self.cube.update)
        self.view.cameraMoved.connect(self._camera_changed)

        # pasek transformacji (przesuń / obróć)
        self.pad = QFrame(v)
        self.pad.setObjectName('bar')
        pl = QHBoxLayout(self.pad)
        pl.setContentsMargins(7, 7, 7, 7)
        pl.setSpacing(7)
        self.pad_buttons = {}
        for name, tip in (('move', 'Przesuń zaznaczony element w osiach X, Y, Z'), ('rotate', 'Obróć zaznaczony element')):
            button = QToolButton()
            button.setObjectName('padTool')
            button.setIcon(ui.style_icon(name, 28))
            button.setIconSize(QSize(28, 28))
            button.setCheckable(True)
            button.setFixedSize(46, 44)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, n=name: self.toggle_mode(n))
            pl.addWidget(button)
            self.pad_buttons[name] = button
        self.grid_button = QToolButton()
        self.grid_button.setObjectName('padTool')
        self.grid_button.setIcon(ui.style_icon('grid', 28))
        self.grid_button.setIconSize(QSize(28, 28))
        self.grid_button.setCheckable(True)
        self.grid_button.setChecked(True)
        self.grid_button.setFixedSize(46, 44)
        self.grid_button.setToolTip('Pokaż / ukryj siatkę')
        self.grid_button.toggled.connect(lambda on: self.view.set_grid_visible(on))
        pl.addWidget(self.grid_button)
        self.persp_button = QToolButton()
        self.persp_button.setObjectName('padTool')
        self.persp_button.setIcon(ui.style_icon('persp', 28))
        self.persp_button.setIconSize(QSize(28, 28))
        self.persp_button.setCheckable(True)
        self.persp_button.setFixedSize(46, 44)
        self.persp_button.setToolTip('Perspektywa włączona / wyłączona. Bez perspektywy (domyślnie) bryły wyglądają jak na rysunku: '
                                     'na widoku prosto na płaszczyznę ścianki zasłaniają to, co jest za nimi.')
        view_settings = settings.read('view') or {}
        self.persp_button.setChecked(bool(view_settings.get('perspective', False)))
        self.view.set_ortho(not self.persp_button.isChecked())
        self.persp_button.toggled.connect(lambda on: (self.view.set_ortho(not on), settings.write('view', dict(perspective=bool(on)))))
        pl.addWidget(self.persp_button)
        self.hist_button = QToolButton()
        self.hist_button.setObjectName('padTool')
        self.hist_button.setIcon(ui.style_icon('history', 28))
        self.hist_button.setIconSize(QSize(28, 28))
        self.hist_button.setCheckable(True)
        self.hist_button.setFixedSize(46, 44)
        self.hist_button.setToolTip('Historia: kroki projektu, powrót do dowolnego etapu')
        self.hist_button.toggled.connect(self._hist_toggled)
        pl.addWidget(self.hist_button)
        ui.shadow(self.pad, 19, 5, 43)

        # historia: pasek kroków na dole okna (każda operacja = krok; klik przeskakuje do stanu z tego momentu)
        self.hist_bar = QFrame(v)
        self.hist_bar.setObjectName('bar')
        hl = QHBoxLayout(self.hist_bar)
        hl.setContentsMargins(8, 6, 8, 6)
        hl.setSpacing(8)
        title = QLabel()
        title.setPixmap(ui.icons.pixmap('x_history', 26))
        hl.addWidget(title)
        self.hist_scroll = QScrollArea()
        self.hist_scroll.setFrameShape(QFrame.NoFrame)
        self.hist_scroll.setWidgetResizable(True)
        self.hist_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.hist_scroll.setFixedHeight(46)
        self.hist_scroll.setStyleSheet('QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }')
        self.hist_inner = QWidget()
        self.hist_row = QHBoxLayout(self.hist_inner)
        self.hist_row.setContentsMargins(0, 0, 0, 0)
        self.hist_row.setSpacing(6)
        self.hist_scroll.setWidget(self.hist_inner)
        hl.addWidget(self.hist_scroll, 1)
        self.hist_revert = QToolButton()
        self.hist_revert.setObjectName('padTool')
        self.hist_revert.setIcon(ui.style_icon('undo', 22))
        self.hist_revert.setIconSize(QSize(22, 22))
        self.hist_revert.setFixedSize(40, 36)
        self.hist_revert.setToolTip('Cofnij ostatnią edycję kroku (przywraca poprzednią historię)')
        self.hist_revert.clicked.connect(self.history_revert)
        hl.addWidget(self.hist_revert)
        self.hist_status = QLabel('')
        self.hist_status.setStyleSheet('color:#187ac1; font-size:12px; font-weight:700; background:transparent;')
        hl.addWidget(self.hist_status)
        self._hist_job = None
        self._hist_folded = set()
        self._hist_trim = False      # po „Cofnij” cofnięte kroki znikają z paska historii (wracają po „Ponów”)
        self._hist_widgets = {}
        self._hist_stretch = False
        self._hist_filter = 'Wszystkie kroki'
        self._hist_tick = QTimer(self)
        self._hist_tick.setInterval(120)
        self._hist_tick.timeout.connect(self._hist_progress)
        self.hist_varbtn = QPushButton('Zmienne')
        self.hist_varbtn.setObjectName('chip')
        self.hist_varbtn.setToolTip('Zmienne projektu i wyrażenia w polach kroków (np. szerokość / 2)')
        self.hist_varbtn.clicked.connect(self.history_variables)
        hl.addWidget(self.hist_varbtn)
        self.hist_menu_button = QPushButton('Warianty')
        self.hist_menu_button.setObjectName('chip')
        self.hist_menu_button.setToolTip('Warianty historii zapisane w projekcie, eksport listy kroków, autozapis')
        self.hist_menu_button.clicked.connect(self.history_menu)
        hl.addWidget(self.hist_menu_button)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(150000)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()
        self.hist_compare = QPushButton('Porównaj')
        self.hist_compare.setObjectName('chip')
        self.hist_compare.setCheckable(True)
        self.hist_compare.setToolTip('Po edycji kroku: pokazuje czerwonym obrysem, jak wyglądał model przed zmianą')
        self.hist_compare.toggled.connect(lambda *_: self._hist_compare_update())
        hl.addWidget(self.hist_compare)
        self.hist_ghost = QPushButton('Pokaż wygaszone')
        self.hist_ghost.setObjectName('chip')
        self.hist_ghost.setCheckable(True)
        self.hist_ghost.setToolTip('Wygaszone szkice (użyte do wyciągnięcia) pokazują się ponownie')
        self.hist_ghost.toggled.connect(lambda *_: self.refresh())
        hl.addWidget(self.hist_ghost)
        self.hist_bar.hide()
        self.hist_edit = QFrame(v)
        self.hist_edit.setObjectName('panel')
        self.hist_edit_layout = QVBoxLayout(self.hist_edit)
        self.hist_edit_layout.setContentsMargins(14, 12, 14, 12)
        self.hist_edit_layout.setSpacing(6)
        self.hist_edit.setFixedWidth(330)
        self.hist_edit.hide()
        self.hist_vars = QFrame(v)
        self.hist_vars.setObjectName('panel')
        self.hist_vars_layout = QVBoxLayout(self.hist_vars)
        self.hist_vars_layout.setContentsMargins(14, 12, 14, 12)
        self.hist_vars_layout.setSpacing(6)
        self.hist_vars.setFixedWidth(360)
        self.hist_vars.hide()
        self._repick = None
        self._lib_action = None        # biblioteka: wskazywanie obiektu na polu albo wybór miejsca wstawienia
        self.libraries = {}
        ui.shadow(self.hist_vars, 19, 5, 43)
        ui.shadow(self.hist_edit, 19, 5, 43)
        self._hist_sig = None
        ui.shadow(self.hist_bar, 19, 5, 43)
        self.pad.adjustSize()

        # okno Przesuń / Obróć: prostokątny panel z grafiką osi (jak pozostałe okna narzędzi)
        self.t_editor = QFrame(v)
        self.t_editor.setObjectName('panel')
        self.t_editor.setFixedWidth(286)
        tl = QVBoxLayout(self.t_editor)
        tl.setContentsMargins(16, 15, 16, 15)
        tl.setSpacing(10)
        self.t_heads = {'move': ui.panel_header('x_move', 'Przesuń', 'Przesunięcie wzdłuż osi X, Y, Z', ui.icons.BLUE, True),
                        'rotate': ui.panel_header('x_rotate', 'Obróć', 'Obrót wokół osi X, Y, Z', ui.icons.BLUE, True)}
        for head in self.t_heads.values():
            tl.addWidget(head)
        self.t_status = _label('Kliknij obiekt, aby go zaznaczyć', 'status')
        tl.addWidget(self.t_status)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.t_spins = []
        self.t_axis_labels = []
        self.t_axis_pics = []
        for i, axis in enumerate('XYZ'):
            pic = QLabel()
            pic.setFixedSize(40, 40)
            label = _label(axis, 'label')
            spin = _spin(0, -1e6, 1e6, 3, 1.0)
            spin.valueChanged.connect(lambda *_: self._transform_changed())
            grid.addWidget(pic, i, 0)
            grid.addWidget(label, i, 1)
            grid.addWidget(spin, i, 2)
            self.t_axis_pics.append(pic)
            self.t_axis_labels.append(label)
            self.t_spins.append(spin)
        grid.setColumnStretch(2, 1)
        tl.addLayout(grid)
        self._buttons(tl, 'Zastosuj', 'Zamknij', self.apply_transform, lambda: self.set_mode(None))
        ui.shadow(self.t_editor, 26, 7, 46)
        self.t_editor.hide()
        self.t_editor.adjustSize()

        # pasek szkicu (jak 'Finish Sketch' w Fusion 360)
        self.sk_bar = QFrame(v)
        self.sk_bar.setObjectName('skbar')
        sl = QHBoxLayout(self.sk_bar)
        sl.setContentsMargins(12, 9, 12, 9)
        sl.setSpacing(10)
        self.sk_badge = QLabel()
        self.sk_badge.setPixmap(ui.icons.badge('sketch', ui.icons.BLUE, 34))
        self.sk_title = QLabel('Szkic')
        self.sk_title.setStyleSheet('font-weight:700;font-size:13px;')
        self.sk_hint = QLabel('')
        self.sk_hint.setStyleSheet('color:#6c869b;')
        finish = QPushButton('✓  Zakończ szkic')
        finish.setObjectName('primary')
        finish.clicked.connect(lambda _=False: self.set_mode(None))
        for w in (self.sk_badge, self.sk_title, self.sk_hint, finish):
            sl.addWidget(w)
        ui.shadow(self.sk_bar, 22, 6, 44)
        self.sk_bar.hide()

        self.origin_label = QLabel(v)
        self.origin_label.setObjectName('origin')
        self.notice = QLabel(v)
        self.notice.setObjectName('notice')
        self.notice.hide()
        ui.shadow(self.notice, 18, 5, 32)
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self.notice.hide)
        self.dim = QLabel(v)
        self.dim.setObjectName('dim')
        self.dim.hide()
        self.dim.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._build_dim_panel()
        self._build_panels()

    def _round(self, icon, tip, callback):
        button = QToolButton(self.view)
        button.setObjectName('round')
        button.setIcon(icon)
        button.setIconSize(QSize(24, 24))
        button.setFixedSize(40, 40)
        button.setToolTip(tip)
        button.clicked.connect(lambda _=False: callback())
        ui.shadow(button, 12, 3, 36)
        return button

    def _build_shape_bar(self):
        self.shape_bar = QFrame(self.view)
        self.shape_bar.setObjectName('toolbar')
        lay = QVBoxLayout(self.shape_bar)
        lay.setContentsMargins(7, 7, 7, 7)
        lay.setSpacing(8)
        self.shape_buttons = {}
        shapes = ui.load_shapes()
        variants: dict[str, list] = {}
        for item in shapes:
            if item['variant']:
                variants.setdefault(item['group'], []).append(item)
        for item in shapes:
            if item['variant']:
                continue
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(0)
            grouped = bool(item['group'] and variants.get(item['group'])) or item['shape'] == 'polygon'
            button = QToolButton()
            button.setObjectName('shapeMain')
            button.setProperty('grouped', 'true' if grouped else 'false')
            button.setCheckable(True)
            button.setFixedSize(34 if grouped else 42, 42)
            button.setIcon(ui.style_icon('s_' + item['shape'], 28))
            button.setIconSize(QSize(28, 28))
            button.setToolTip(item['title'])
            button.clicked.connect(lambda _=False, name=item['shape']: self._tool_clicked(name))
            hl.addWidget(button)
            self.shape_buttons[item['shape']] = button
            if grouped:
                more = QToolButton()
                more.setObjectName('shapeExpand')
                more.setText('▾')
                more.setFixedSize(15, 42)
                more.setToolTip('Warianty')
                if item['shape'] == 'polygon':
                    more.setToolTip('Liczba kątów wielokąta')
                    more.clicked.connect(lambda _=False, b=more: self._sides_menu(b))
                else:
                    more.clicked.connect(lambda _=False, g=item['group'], b=more, main=button: self._variants_menu(variants[g], b, main))
                hl.addWidget(more)
            lay.addWidget(row)
        ui.shadow(self.shape_bar, 15, 4, 36)
        self.shape_bar.adjustSize()
        self.shape_bar.hide()

    VARIANT_HINTS = {'rect': 'Przeciągnij przekątną', 'centerRect': 'Środek i narożnik', 'rect3': 'Podstawa i wysokość',
                     'circle': 'Środek i punkt na okręgu', 'circleTangent2': 'Kliknij dwie linie i wielkość', 'circle2': 'Końce średnicy',
                     'circle3': 'Trzy punkty na okręgu'}

    VARIANT_ICONS = {'rect': 'v_rect2', 'centerRect': 'v_rectC', 'rect3': 'v_rect3', 'circle': 'v_circle', 'circle2': 'v_circle2', 'circle3': 'v_circle3',
                     'circleTangent2': 'v_tan'}

    def _popup_toggle(self, anchor):
        """Strzałka przy otwartym okienku wariantów / liczby kątów: okienko się chowa i nie otwiera ponownie."""
        import time
        pop = self._popup
        if pop is None or getattr(pop, 'anchor', None) is not anchor:
            return False
        try:
            if pop.isVisible():
                pop.close()
                return True
        except RuntimeError:
            return False
        return pop.closed_by_anchor and time.monotonic() - getattr(pop, 'closed_at', 0) < .4   # to samo kliknięcie, które je zamknęło

    def _set_sides(self, value):
        self.sides = int(value)
        self.shape_buttons['polygon'].setToolTip(f'Wielokąt ({self.sides} kątów)')
        if self.points and self.tool == 'polygon' and self.last_uv is not None:
            self.sketch_moved(self.sketch_plane, *self.last_uv)

    def _sides_menu(self, anchor):
        """Strzałka przy wielokącie: grafika i pole liczby kątów (3-64). Ponowne kliknięcie strzałki chowa okienko."""
        if self._popup_toggle(anchor):
            self._popup = None
            return
        if self.tool != 'polygon' and self.mode == 'sketch':
            self.choose_tool('polygon')
        menu = ui.SidesPopup(self, int(self.sides), self._set_sides)
        menu.anchor = anchor
        self._popup = menu
        menu.popup_at(anchor.mapToGlobal(QPoint(anchor.width() + 8, 0)))

    def _variants_menu(self, items, anchor, main):
        if self._popup_toggle(anchor):
            self._popup = None
            return
        entries = []
        for item in items:
            name = item['shape']
            icon = ui.icons.pixmap(self.VARIANT_ICONS.get(name, 'v_rect2'), 34)
            entries.append((icon, VARIANT_LABELS.get(name, item['title']), self.VARIANT_HINTS.get(name, ''), lambda n=name: self.choose_tool(n, main)))
        menu = ui.RichMenu(self, entries, 'Sposób rysowania', 290)
        menu.anchor = anchor
        self._popup = menu
        menu.popup_at(anchor.mapToGlobal(QPoint(anchor.width() + 8, 0)))

    def _build_dim_panel(self):
        self.dim_panel = QFrame(self.view)
        self.dim_panel.setObjectName('dimpanel')
        lay = QHBoxLayout(self.dim_panel)
        lay.setContentsMargins(13, 11, 13, 11)
        lay.setSpacing(8)
        self.dim_labels, self.dim_edits = [], []
        for _ in range(3):
            col = QVBoxLayout()
            col.setSpacing(4)
            label = QLabel('')
            edit = QLineEdit()
            edit.textChanged.connect(lambda *_: self._timers['dim'].start())
            edit.returnPressed.connect(self.apply_typed)
            col.addWidget(label)
            col.addWidget(edit)
            lay.addLayout(col)
            self.dim_labels.append(label)
            self.dim_edits.append(edit)
        side = QVBoxLayout()
        side.setSpacing(6)
        help_ = QLabel('Tab: kolejne pole\nEnter: zatwierdź\nEsc: anuluj')
        help_.setObjectName('help')
        ok = QPushButton('Zatwierdź')
        ok.setObjectName('primary')
        ok.setCursor(Qt.PointingHandCursor)
        ok.setFocusPolicy(Qt.NoFocus)
        ok.clicked.connect(lambda _=False: self.apply_typed())
        side.addWidget(help_)
        side.addWidget(ok)
        lay.addLayout(side)
        self.dim_ok = ok
        ui.shadow(self.dim_panel, 20, 5, 37)
        self.dim_panel.hide()
        self.dim_edit = self.dim_edits[0]   # zgodność wsteczna
        self._dim_target = None
        self.dim_panel.installEventFilter(self)

    def _build_panels(self):
        # --- wyciągnięcie: panel opcji + górny pasek ---
        self.ex_panel, lay = self._panel(312, 'Wyciągnięcie', 'x_extrude', 'Profil lub ściana → bryła', plain=True)
        lay.setSpacing(11)
        self.ex_op = ui.Segmented([('Nowa', 'new', 'new'), ('Połącz', 'join', 'join'), ('Wytnij', 'cut', 'cut'), ('Wspólna', 'intersect', 'intersect')], 32)
        self._field(lay, 'Operacja', self.ex_op)
        self.ex_extent = ui.Segmented([('Na odległość', 'dist', 'ex_dist'), ('Do elementu', 'upto', 'ex_upto')], 32)
        self.ex_extent.setToolTip('Do elementu: po wybraniu profilu kliknij płaszczyznę, ścianę, krawędź albo punkt - bryła sięga do jego wysokości.')
        self._field(lay, 'Zakres', self.ex_extent)
        self.ex_target = None       # wskazany element (Do elementu): dict(kind, point, label)
        self.ex_join_label=_label('Połącz z bryłą')
        lay.addWidget(self.ex_join_label)
        self.ex_join_scope=ui.Segmented([('Początkową','source','join'),('Docelową','target','join')],32)
        lay.addWidget(self.ex_join_scope)
        self.ex_join_scope._buttons[0].setToolTip('Wyciągnięcie zostaje dołączone do bryły, z której wychodzi profil.')
        self.ex_join_scope._buttons[1].setToolTip('Wyciągnięcie zostaje dołączone do wskazanej bryły docelowej.')
        self.ex_join_label.hide();self.ex_join_scope.hide()
        self.ex_dir_label = _label('Kierunek')
        lay.addWidget(self.ex_dir_label)
        self.ex_dir = ui.Segmented([('Jedna strona', 'one', 'one'), ('Symetrycznie', 'symmetric', 'sym'), ('Dwie strony', 'two', 'two'), ('Oba końce', 'ends', 'ends')], 32)
        lay.addWidget(self.ex_dir)
        self.ex_status = _label('Kliknij zamknięty profil szkicu lub płaską ścianę bryły.', 'status')
        lay.addWidget(self.ex_status)
        self.ex_bar = QFrame(self.view)
        self.ex_bar.setObjectName('bar')
        bar = QHBoxLayout(self.ex_bar)
        bar.setContentsMargins(12, 10, 12, 10)
        bar.setSpacing(8)
        strong = QLabel('Wyciągnięcie')
        strong.setStyleSheet('font-weight:700;font-size:13px;color:#000;')
        bar.addWidget(strong)
        bar.addWidget(QLabel('Odległość (mm)'))
        self.ex_value = _spin(10, -1e5, 1e5, 3, 1.0)
        self.ex_value.setFixedWidth(105)
        bar.addWidget(self.ex_value)
        self.ex_target_label = QLabel('')
        self.ex_target_label.setStyleSheet('color:#c46f00;font-weight:600;')
        bar.addWidget(self.ex_target_label)
        self.ex_target_label.hide()
        self.ex_second_label = QLabel('Druga strona (mm)')
        bar.addWidget(self.ex_second_label)
        self.ex_second = _spin(10, 0, 1e5, 3, 1.0)
        self.ex_second.setFixedWidth(105)
        bar.addWidget(self.ex_second)
        for text, cb in (('Zastosuj', self.apply_extrude), ('Zamknij', lambda: self.set_mode(None))):
            b = QPushButton(text)
            b.setObjectName('primary' if text == 'Zastosuj' else 'ghost')
            b.clicked.connect(lambda _=False, f=cb: f())
            bar.addWidget(b)
        ui.shadow(self.ex_bar, 24, 7, 64)
        self.ex_bar.hide()
        for w in (self.ex_value, self.ex_second):
            w.valueChanged.connect(lambda *_: self._ex_value_changed())
        self.ex_dir.currentIndexChanged.connect(self._ex_dir_changed)
        self.ex_extent.currentIndexChanged.connect(self._ex_extent_changed)
        self.ex_join_scope.currentIndexChanged.connect(lambda *_:self._timers['extrude'].start())
        self.ex_op.currentIndexChanged.connect(lambda *_: (self._ex_op_user_changed(), self._timers['extrude'].start()))
        self.ex_second_label.hide()
        self.ex_second.hide()

        # --- obrót ---
        self.rev_panel, lay = self._panel(312, 'Obrót', 'x_revolve', 'Profil wokół osi → bryła obrotowa', plain=True)
        self.rev_step1 = ui.StepRow(1, 'x_area', 'Profil (szkic lub ściana)', plain=True)
        self.rev_step2 = ui.StepRow(2, 'x_axis', 'Oś obrotu', plain=True)
        lay.addWidget(self.rev_step1)
        lay.addWidget(self.rev_step2)
        self.rev_axis = ui.Segmented([('Pozioma', 'u', 'ax_u'), ('Pionowa', 'v', 'ax_v'), ('Wskaż', 'line', 'ax_line')], 30)
        self.rev_axis.setCurrentIndex(1)
        self._field(lay, 'Oś obrotu', self.rev_axis)
        self.rev_axis.setToolTip('Pozioma / pionowa oś przez początek szkicu albo Wskaż - prosta linia szkicu lub krawędź bryły.')
        self.rev_op = ui.Segmented([('Nowa', 'new', 'new'), ('Połącz', 'join', 'join'), ('Wytnij', 'cut', 'cut'), ('Wspólna', 'intersect', 'intersect')], 32)
        self._field(lay, 'Operacja', self.rev_op)
        self.rev_angle = _spin(360, 1, 360, 1, 15)
        self.rev_angle_pic = self._pic_field(lay, 'Kąt obrotu (°)', 'rv_angle', self.rev_angle, '360° - pełna bryła, mniej - wycinek.')
        self.rev_status = _label('Kliknij zamknięty profil szkicu lub płaską ścianę bryły.', 'status')
        lay.addWidget(self.rev_status)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_revolve, lambda: self.set_mode(None))
        self.rev_axis.currentIndexChanged.connect(self._rev_axis_changed)
        self.rev_op.currentIndexChanged.connect(lambda *_: self._timers['revolve'].start())
        self.rev_angle.valueChanged.connect(lambda *_: self._timers['revolve'].start())

        # --- skorupa ---
        self.shell_panel, lay = self._panel(312, 'Skorupa', 'x_shell', 'Wydrąż bryłę · otwórz ściany', plain=True)
        self.sh_step1 = ui.StepRow(1, 'x_object', 'Bryła', plain=True)
        self.sh_step2 = ui.StepRow(2, 'x_area', 'Ściany do otwarcia (opcjonalnie)', plain=True)
        lay.addWidget(self.sh_step1)
        lay.addWidget(self.sh_step2)
        self.sh_thick = _spin(2, .01, 1e5, 3, .5)
        self.sh_thick_pic = self._pic_field(lay, 'Grubość ścianki (mm)', 'sh_wall', self.sh_thick, 'Grubość ścianek, które zostają po wydrążeniu.')
        self.sh_dir = ui.Segmented([('Do wewnątrz', 'in', 'sh_in'), ('Na zewnątrz', 'out', 'sh_out')], 30)
        self._field(lay, 'Kierunek', self.sh_dir)
        self.sh_status = _label('Kliknij bryłę, którą chcesz wydrążyć.', 'status')
        lay.addWidget(self.sh_status)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_shell, lambda: self.set_mode(None))
        self.sh_thick.valueChanged.connect(lambda *_: (self._place_shell_handle(), self._timers['shell'].start()))
        self.sh_dir.currentIndexChanged.connect(lambda *_: (self._place_shell_handle(), self._timers['shell'].start()))

        # --- gwint ---
        from . import threads as th
        self.th_pick = None             # wybrany walec: id bryły i opis (oś, promień, zakres, otwór / wałek)
        self.th_extra = []              # kolejne walce dodane z Shift (ten sam gwint na kilku otworach naraz)
        self.thread_panel, lay = self._panel(330, 'Gwint', 'x_thread', 'Otwór lub wałek · szybki gwint kosmetyczny', plain=True, scroll=True)
        self.th_step1 = ui.StepRow(1, 'x_object', 'Otwór albo wałek', plain=True)
        lay.addWidget(self.th_step1)
        self.th_standard = QComboBox()
        for key, info in th.STANDARDS.items():
            self.th_standard.addItem(info['title'], key)
        self._field(lay, 'Rodzaj gwintu', self.th_standard)
        self.th_size = QComboBox()
        self.th_size.setMaxVisibleItems(16)
        self._field(lay, 'Rozmiar', self.th_size)
        self.th_info = QLabel('—')
        self.th_info.setObjectName('readout')
        self.th_info.setWordWrap(True)
        self.th_info.setStyleSheet('QLabel#readout{background:#f3f6fa;border:1.4px solid #d6e0ea;border-radius:8px;padding:7px 10px;font-weight:700;color:#27415a;}')
        lay.addWidget(self.th_info)
        self.th_auto = QCheckBox('Dopasuj gwint do otworu automatycznie')
        self.th_auto.setChecked(True)
        self.th_auto.setToolTip('Włączone: rozmiar dobiera się do średnicy otworu / wałka. Wyłączone: wybierasz rozmiar sam, '
                                'a otwór / wałek zostanie dopasowany do gwintu przy zatwierdzeniu.')
        lay.addWidget(self.th_auto)
        self.th_side = ui.Segmented([('Wewnętrzny', 'in', 'th_in'), ('Zewnętrzny', 'out', 'th_out')], 30)
        self._field(lay, 'Gwint', self.th_side)
        self.th_hand = ui.Segmented([('Prawy', 'right', 'th_rh'), ('Lewy (LH)', 'left', 'th_lh')], 30)
        self._field(lay, 'Kierunek zwojów', self.th_hand)
        self.th_extent = ui.Segmented([('Cała długość', 'full', 'th_full'), ('Określona', 'len', 'th_len')], 30)
        self._field(lay, 'Długość gwintu', self.th_extent)
        self.th_len_box = QWidget()
        box = QVBoxLayout(self.th_len_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.th_length = _spin(10, .1, 1e5, 2, 1)
        self.th_length.setToolTip('Długość gwintu; można też przeciągać strzałki na końcach w widoku.')
        self._field(box, 'Długość (mm)', self.th_length)
        self.th_offset = _spin(0, 0, 1e5, 2, 1)
        self.th_offset.setToolTip('Odsunięcie początku gwintu od końca otworu / wałka.')
        self._field(box, 'Odsunięcie od początku (mm)', self.th_offset)
        lay.addWidget(self.th_len_box)
        self.th_real = QCheckBox('Od razu prawdziwy gwint (zwoje w bryle)')
        self.th_real.setChecked(False)
        self.th_real.setToolTip('Zamiast lekkiego gwintu kosmetycznego od razu tworzy prawdziwe zwoje w modelu - '
                                'wolniej i cięższy model; gwint kosmetyczny i tak zamienia się w prawdziwy przy eksporcie STL / STEP.')
        lay.addWidget(self.th_real)
        self.th_convert = QPushButton('Zamień wirtualny gwint na prawdziwy')
        self.th_convert.setToolTip('Wskazany otwór / wałek ma gwint kosmetyczny - zamień go na taki sam, ale prawdziwy (zwoje w bryle).')
        self.th_convert.clicked.connect(lambda _=False: self.convert_thread())
        self.th_convert.hide()
        lay.addWidget(self.th_convert)
        self.th_status = _label('Kliknij otwór albo wałek (walcową ścianę bryły). Shift + klik dodaje kolejne.', 'status')
        lay.addWidget(self.th_status)
        self._buttons(self.thread_panel.footer, 'Zastosuj', 'Zamknij', self.apply_thread, lambda: self.set_mode(None))
        self.th_standard.currentIndexChanged.connect(lambda *_: self._th_standard_changed())
        self.th_size.currentIndexChanged.connect(lambda *_: self._th_size_changed())
        self.th_auto.toggled.connect(lambda *_: self._th_fit())
        self.th_side.currentIndexChanged.connect(lambda *_: self._th_fit())
        self.th_hand.currentIndexChanged.connect(lambda *_: self._th_update())
        self.th_extent.currentIndexChanged.connect(lambda *_: self._th_update())
        self.th_length.valueChanged.connect(lambda *_: self._th_update())
        self.th_offset.valueChanged.connect(lambda *_: self._th_update())
        self._th_standard_changed()

        # --- blacha: konwersja i kołnierz ---
        self.sheet_meta = {}        # id bryły -> normalna i grubość blachy (z konwersji), potrzebne do kołnierzy
        self._sheet_cmd = None      # Rozłóż / Zegnij / DXF czekające na wskazanie blachy (tryb 'sheetpick')
        self._plyfold_cmd = None   # Rozłóż / Złóż płyty czekające na wskazanie płyty (tryb 'plyfoldpick')
        self.sheet_pick = None
        self.fl_pick = None
        self.sheet_panel, lay = self._panel(312, 'Konwertuj na blachę', 'x_sheet', 'Płaski prostokąt → blacha do gięcia', plain=True, scroll=True)
        self.sheet_pic = QLabel()
        self.sheet_pic.setFixedHeight(84)
        self.sheet_pic.setAlignment(Qt.AlignCenter)
        self.sheet_pic.setPixmap(ui.icons.pixmap('sh_convert', 170))       # rysunek zajmuje środkowy pas kwadratu - widoczny pas 84 px
        self.sheet_pic.setToolTip('Kliknięta ściana staje się górą blachy, grubość to odległość do ściany przeciwnej.')
        lay.addWidget(self.sheet_pic)
        self.sheet_t = QLabel('—')
        self.sheet_dims = QLabel('—')
        for text, kind, value, tip in (('Grubość blachy', 'sh_thick', self.sheet_t, 'Odległość od klikniętej ściany do ściany przeciwnej.'),
                                       ('Wymiary płyty', 'sh_dims', self.sheet_dims, 'Wymiary klikniętej prostokątnej ściany.')):
            value.setObjectName('readout')
            value.setStyleSheet('QLabel#readout{background:#f3f6fa;border:1.4px solid #d6e0ea;border-radius:8px;padding:7px 10px;font-weight:700;color:#27415a;}')
            self._pic_field(lay, text, kind, value, tip)
        self.sheet_status = _label('Kliknij płaską prostokątną ścianę bryły.', 'status')
        lay.addWidget(self.sheet_status)
        self._buttons(self.sheet_panel.footer, 'Zamień na blachę', 'Zamknij', self.apply_sheet, lambda: self.set_mode(None))

        self.flange_panel, lay = self._panel(312, 'Kołnierz', 'x_flange', 'Wyciągnij krawędź blachy', plain=True, scroll=True)

        self.fl_radius = _spin(FLANGE_DEFAULT['radius'], .01, 1e5, 3, .5)
        self.fl_radius_pic = self._pic_field(lay, 'Promień gięcia (mm)', 'fl_radius', self.fl_radius, 'Wewnętrzny promień gięcia (promień stempla).')
        self.fl_angle = _spin(FLANGE_DEFAULT['angle'], .1, 180, 2, 1)
        self.fl_angle_pic = self._pic_field(lay, 'Kąt (°)', 'fl_angle', self.fl_angle, 'Kąt gięcia kołnierza względem blachy.')
        self.fl_length = _spin(FLANGE_DEFAULT['length'], .01, 1e5, 3, 1)
        self.fl_length_pic = self._pic_field(lay, 'Długość kołnierza (mm)', 'fl_length', self.fl_length, 'Długość kołnierza mierzona od wybranej strony blachy do jego końca.')
        self.fl_datum = ui.Segmented([('Zewnętrzna', 'outer', 'dl_outer'), ('Wewnętrzna', 'inner', 'dl_inner')], 40)
        self._field(lay, 'Długość mierzona od strony', self.fl_datum)
        tips = {'outer': 'Zewnętrzna: długość od wierzchołka kołnierza do zewnętrznej strony blachy (z grubością); przy kolejnym gięciu '
                         'od zewnętrznej do zewnętrznej strony. Płyta ma wymiar zewnętrzny gotowej blachy. Kąt rozwarty: do środka zewnętrznego łuku.',
                'inner': 'Wewnętrzna: długość od wierzchołka kołnierza do wewnętrznej strony blachy (bez grubości); przy kolejnym gięciu '
                         'od wewnętrznej do wewnętrznej strony. Płyta ma wymiar wewnętrzny gotowej blachy. Kąt rozwarty: do środka wewnętrznego łuku.'}
        for button, key in zip(self.fl_datum._buttons, self.fl_datum._data):
            button.setToolTip(tips[key])
        self.fl_reverse = QCheckBox('Odwróć kierunek gięcia')
        lay.addWidget(self.fl_reverse)
        self.fl_status = _label('Kliknij Zaginaj, potem klikaj krawędzie blachy.', 'status')
        lay.addWidget(self.fl_status)
        self._bend_buttons(self.flange_panel.footer, 'fl', self.save_flange_settings, self.reset_flange_settings,
                           'Zapamiętuje ustawienia kołnierza (zostają także po ponownym uruchomieniu programu).',
                           'Przywraca ustawienia domyślne: R 0,5 mm, 90°, 5 mm, od strony zewnętrznej.')
        self.fl_armed = False
        self._load_flange_settings()

        self.hem_panel, lay = self._panel(312, 'Zawinięcie', 'x_hem', 'Zawija krawędź blachy o 180°', plain=True, scroll=True)
        self.hm_radius = _spin(HEM_DEFAULT['radius'], .01, 1e5, 3, .5)
        self.hm_radius_pic = self._pic_field(lay, 'Promień gięcia (mm)', 'hm_radius', self.hm_radius,
                                             'Promień zawinięcia; program zmniejsza go do połowy szczeliny, gdy szczelina jest mniejsza.')
        self.hm_length = _spin(HEM_DEFAULT['length'], .01, 1e5, 3, 1)
        self.hm_length_pic = self._pic_field(lay, 'Maksymalna długość zawinięcia (mm)', 'hm_length', self.hm_length,
                                             'Długość odcinka powrotnego; program skraca ją do miejsca na kołnierzu i przy sąsiednich zawinięciach.')
        self.hm_gap = _spin(HEM_DEFAULT['gap'], 0.1, 1e5, 3, .1)
        self.hm_gap_pic = self._pic_field(lay, 'Szczelina od powierzchni (mm, min 0,1)', 'hm_gap', self.hm_gap,
                                          'Odstęp między powierzchnią blachy a odcinkiem powrotnym zawinięcia.')
        self.hm_status = _label('Kliknij Zaginaj, potem klikaj krawędzie blachy.', 'status')
        lay.addWidget(self.hm_status)
        self._bend_buttons(self.hem_panel.footer, 'hm', self.save_hem_settings, self.reset_hem_settings,
                           'Zapamiętuje ustawienia zawinięcia (zostają także po ponownym uruchomieniu programu).',
                           'Przywraca ustawienia domyślne: R 2 mm, długość 10 mm, szczelina 0,1 mm.')
        self._load_hem_settings()
        self._style_bend_button()

        # --- reguły blach: szczelina i wycięcia w narożnikach (osobny panel, dotyczy kołnierzy) ---
        self.rules_panel, lay = self._panel(312, 'Reguły blach', 'x_rules', 'Szczelina i wycięcia w narożnikach', plain=True, scroll=True)
        self.fl_gap = _spin(RULES_DEFAULT['gap'], 0, 1e5, 3, .1)
        lay.addWidget(_label('Szczelina między kołnierzami (mm)'))
        gap_row = QHBoxLayout()
        gap_row.setSpacing(12)
        self.fl_gap_pic = QLabel()
        self.fl_gap_pic.setFixedSize(64, 64)
        self.fl_gap_pic.setPixmap(ui.icons.pixmap('rl_gap', 64))
        self.fl_gap_pic.setToolTip('Odstęp między końcami dwóch kołnierzy spotykających się w narożniku.')
        gap_row.addWidget(self.fl_gap_pic)
        gap_row.addWidget(self.fl_gap, 1)
        lay.addLayout(gap_row)
        self.fl_relief = ui.Segmented([('Brak', 'none', 'rl_none'), ('Kwadrat', 'square', 'rl_sq'), ('Okrąg', 'round', 'rl_round')], 34)
        self._field(lay, 'Wycięcie w narożniku', self.fl_relief)
        self.fl_relief_size = _spin(3, 0, 1e5, 3, .5)
        self._field(lay, 'Wielkość wycięcia (mm)', self.fl_relief_size)
        self.fl_kfactor = _spin(shm.K_DEFAULT, 0, .5, 3, .01)
        self.fl_kfactor.setToolTip('K = położenie warstwy obojętnej / grubość. Dobierz na podstawie prób gięcia materiału.')
        self._field(lay, 'Współczynnik K rozwinięcia', self.fl_kfactor)
        self.fl_joint = ui.Segmented([('Równolegle', 'parallel', 'rl_par'),
                                      ('Blacharskie', 'sheet', 'rl_sheet')], 30)
        self.fl_joint.setCurrentIndex(1)
        self.fl_joint.setToolTip('Równolegle: jedna ściana dochodzi do powierzchni drugiej, również przy kolejnych gięciach. Blacharskie: proste końce pionowych ścian, ukosy między poziomymi kołnierzami i dopasowane wycięcia na łukach gięcia.')
        self._field(lay, 'Łączenie kołnierzy w narożniku', self.fl_joint)
        self.fl_outside = QCheckBox('Długość kołnierza jako wymiar zewnętrzny')      # starsze projekty; nowe kołnierze mają odniesienie w panelu Kołnierz
        self.fl_outside.setToolTip('Podajesz długość od zewnętrznej powierzchni blachy do końca kołnierza. Program odejmuje część gięcia.')
        self.fl_outside.setVisible(False)
        self.rl_status = _label('Zaznacz blachę albo kliknij „Zastosuj do blachy” i wskaż ją.', 'status')
        lay.addWidget(self.rl_status)
        self.rl_pick = False         # „Zastosuj do blachy” bez zaznaczenia: następne kliknięcie wskazuje blachę
        self.fl_apply_rules = QPushButton('Zastosuj do blachy')
        self.fl_apply_rules.clicked.connect(lambda _=False: self.apply_sheet_rules())
        self.rules_panel.footer.addWidget(self.fl_apply_rules)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.rl_ok, self.rl_close, self.rl_reset = QPushButton('Zastosuj'), QPushButton('Zamknij'), QPushButton('Reset')
        self.rl_ok.setObjectName('primary')
        self.rl_ok.setToolTip('Zatwierdza ustawienia i włącza gięcie (Kołnierz): kolejne gięcia dostaną te reguły.')
        self.rl_reset.setToolTip('Przywraca ustawienia domyślne.')
        self.rl_ok.clicked.connect(lambda _=False: self.confirm_sheet_rules())
        self.rl_close.clicked.connect(lambda _=False: self.set_mode(None))
        self.rl_reset.clicked.connect(lambda _=False: self.reset_sheet_rules())
        for b in (self.rl_ok, self.rl_close, self.rl_reset):
            row.addWidget(b, 1)
        self.rules_panel.footer.addLayout(row)
        # --- przeciągnięcie ---
        self.sweep_panel, lay = self._panel(312, 'Przeciągnięcie', 'x_sweep', 'Profil wzdłuż ścieżki → bryła', plain=True)
        self.sw_step1 = ui.StepRow(1, 'x_area', 'Profil (szkic lub ściana)', plain=True)
        self.sw_step2 = ui.StepRow(2, 'x_pat_path', 'Ścieżka (linia, łuk lub krawędź)', plain=True)
        lay.addWidget(self.sw_step1)
        lay.addWidget(self.sw_step2)
        self.sw_op = ui.Segmented([('Nowa', 'new', 'new'), ('Połącz', 'join', 'join'), ('Wytnij', 'cut', 'cut'), ('Wspólna', 'intersect', 'intersect')], 32)
        self._field(lay, 'Operacja', self.sw_op)
        self.sw_status = _label('Kliknij zamknięty profil szkicu lub płaską ścianę bryły.', 'status')
        lay.addWidget(self.sw_status)
        self.sw_again = QPushButton('Wskaż ścieżkę ponownie')
        self.sw_again.setObjectName('chip')
        self.sw_again.clicked.connect(lambda _=False: self._sw_reset_path())
        lay.addWidget(self.sw_again)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_sweep, lambda: self.set_mode(None))
        self.sw_op.currentIndexChanged.connect(lambda *_: self._timers['sweep'].start())

        # --- wyciągnięcie złożone ---
        self.loft_panel, lay = self._panel(312, 'Wyciągnięcie złożone', 'x_loft', 'Bryła przez kilka profili', plain=True)
        self.lf_step1 = ui.StepRow(1, 'x_area', 'Profile (kolejno)', plain=True)
        self.lf_step2 = ui.StepRow(2, 'x_object', 'Punkt końcowy', plain=True)
        lay.addWidget(self.lf_step1)
        lay.addWidget(self.lf_step2)
        self.lf_kind = ui.Segmented([('Profile', 'profiles', 'lf_profiles'), ('Do punktu', 'point', 'lf_point')], 30)
        self._field(lay, 'Koniec bryły', self.lf_kind)
        self.lf_ruled = ui.Segmented([('Gładko', 'smooth', 'lf_smooth'), ('Prosto', 'ruled', 'lf_ruled')], 30)
        self._field(lay, 'Przejście między profilami', self.lf_ruled)
        self.lf_op = ui.Segmented([('Nowa', 'new', 'new'), ('Połącz', 'join', 'join'), ('Wytnij', 'cut', 'cut'), ('Wspólna', 'intersect', 'intersect')], 32)
        self._field(lay, 'Operacja', self.lf_op)
        self.lf_status = _label('Kliknij kolejne profile (ponowne kliknięcie usuwa profil).', 'status')
        lay.addWidget(self.lf_status)
        self.lf_last = QPushButton('Usuń ostatni profil')
        self.lf_last.setObjectName('chip')
        self.lf_last.clicked.connect(lambda _=False: self._lf_drop_last())
        lay.addWidget(self.lf_last)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_loft, lambda: self.set_mode(None))
        self.lf_kind.currentIndexChanged.connect(lambda *_: self._lf_kind_changed())
        self.lf_ruled.currentIndexChanged.connect(lambda *_: self._timers['loft'].start())
        self.lf_op.currentIndexChanged.connect(lambda *_: self._timers['loft'].start())

        # --- pomiary ---
        self.ms_panels, self.ms_status = {}, {}
        for key, title, kind, sub, desc in (
                ('mdist', 'Odległość', 'x_mdist', 'Dwa punkty', 'Kliknij dwa punkty (narożnik, koniec linii albo punkt na powierzchni bryły). Program poda odległość i jej składowe w osiach X, Y, Z.'),
                ('mangle', 'Kąt', 'x_mangle', 'Punkty, krawędzie lub ściany', 'Wybierz trzy punkty (drugi jest wierzchołkiem kąta), dwie proste krawędzie albo dwie płaskie ściany.'),
                ('mrad', 'Promień i średnica', 'x_mrad', 'Okrąg, łuk lub krawędź', 'Kliknij okrągłą krawędź bryły albo okrąg lub łuk szkicu. Prosta krawędź pokaże swoją długość.'),
                ('mprops', 'Właściwości', 'x_mprops', 'Bryła lub szkic', 'Kliknij bryłę: objętość, pole powierzchni, wymiary i środek masy. Kliknij szkic: pole i obwód.')):
            panel, lay = self._panel(380, title, kind, sub, plain=True, scroll=True)
            lay.addWidget(_label(desc, 'small'))
            if key=='mangle':
                self.ms_angle_kind=QComboBox()
                for text,value in [('Trzy punkty','points'),('Dwie proste krawędzie','edges'),('Dwie płaskie ściany','faces')]:self.ms_angle_kind.addItem(text,value)
                lay.addWidget(self.ms_angle_kind)
                self.ms_angle_kind.currentIndexChanged.connect(lambda *_:self._measure_reset())
            self.ms_hover_label=getattr(self,'ms_hover_label',{})
            hover=_label('Najedź na element, aby zobaczyć, co zostanie zmierzone.','small');hover.setWordWrap(True)
            lay.addWidget(hover);self.ms_hover_label[key]=hover
            status = _label('Wskaż obiekt na polu roboczym.', 'status')
            status.setTextFormat(Qt.RichText)
            lay.addWidget(status)
            self._buttons(panel.footer, 'Wyczyść pomiar', 'Zamknij', lambda: self._measure_reset(), lambda: self.set_mode(None))
            self.ms_panels[key], self.ms_status[key] = panel, status

        # --- rysunek techniczny ---
        self.dr_panels = {}
        for key, title, kind, sub, desc in (
                ('drawing', 'Rysunek techniczny', 'x_drawing', 'Wskaż bryłę', 'Kliknij bryłę (podświetla się na niebiesko). Otworzy się osobne okno: wybierzesz rzuty, wymiary i arkusz, zmierzysz dowolne miejsce rysunku i zapiszesz go jako PDF, DXF, SVG lub JPG.'),
                ('autodrawing', 'Rysunek automatyczny', 'x_autodrawing', 'Wskaż bryłę', 'Kliknij bryłę. Program sam dobierze rzuty, arkusz, skalę i wymiary, a zapyta tylko o format i miejsce zapisu.'),
                ('sheetdrawing', 'Rysunek blachy do gięcia', 'x_sheetdrawing', 'Wskaż blachę', 'Kliknij blachę (zgiętą albo rozłożoną). Powstanie rozwinięcie widziane od góry blachy: wymiary całości, odległości linii gięcia od krawędzi i między sobą, kierunek, kąt i promień każdego gięcia oraz grubość blachy.'),
                ('plydrawing', 'Rysunek płyt', 'x_plydrawing', 'Wskaż płytę pudełka', 'Kliknij dowolną płytę pudełka albo mebla ze sklejki. Wszystkie płyty z jego grupy zostaną rozłożone płasko obok siebie - każda z nazwą i wymiarami; widok izometryczny pokazuje całość złożoną.')):
            panel, lay = self._panel(312, title, kind, sub, plain=True)
            pic = QLabel()
            pic.setFixedHeight(96)
            pic.setAlignment(Qt.AlignCenter)
            pic.setPixmap(ui.icons.pixmap('dr_' + key, 96))
            pic.setToolTip(desc)
            lay.addWidget(pic)
            lay.addWidget(_label('Kliknij ' + {'sheetdrawing': 'blachę', 'plydrawing': 'płytę ze sklejki'}.get(key, 'bryłę') + ' na polu roboczym.', 'status'))
            close = QPushButton('Zamknij')
            close.clicked.connect(lambda _=False: self.set_mode(None))
            lay.addWidget(close)
            self.dr_panels[key] = panel
        self._drawing_windows = []

        # --- boolean ---
        self.bool_panel, lay = self._panel(312, 'Boolean / CSG', 'x_bool', 'Łączenie, odejmowanie, część wspólna', plain=True)
        self.bool_op = ui.Segmented([('Suma', 'union', 'union'), ('Różnica', 'subtract', 'subtract'), ('Część wspólna', 'intersect', 'common')], 36)
        self._field(lay, 'Operacja', self.bool_op)
        self.bool_status = _label('', 'status')
        lay.addWidget(self.bool_status)
        self.bool_keep = QCheckBox('Zachowaj bryły-narzędzia')
        lay.addWidget(self.bool_keep)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_bool, lambda: self.set_mode(None))
        self.bool_op.currentIndexChanged.connect(lambda *_: self._timers['bool'].start())

        # --- edytuj bryłę ---
        self.mod_panel, lay = self._panel(312, 'Edytuj bryłę', 'x_mod', 'Zaokrąglenie i fazowanie krawędzi', plain=True)
        self.mod_kind = ui.Segmented([('Zaokrąglij', 'fillet', 'fillet'), ('Fazuj', 'chamfer', 'chamfer')], 36)
        self._field(lay, 'Operacja', self.mod_kind)
        self.mod_size = _spin(3, .01, 1e5, 3, .5)
        self.mod_size_pic = self._pic_field(lay, 'Promień zaokrąglenia (mm)', 'md_fillet', self.mod_size, 'Promień zaokrąglenia albo szerokość fazy.')
        self.mod_label = lay.itemAt(lay.count() - 2).widget()
        self.mod_status = _label('Kliknij krawędź lub narożnik; dwuklik w ścianę zaznacza cały jej obwód.', 'status')
        lay.addWidget(self.mod_status)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_mod, lambda: self.set_mode(None))
        self.mod_size.valueChanged.connect(lambda *_: self._mod_value_changed())
        self.mod_kind.currentIndexChanged.connect(self._mod_kind_changed)

        # --- odbicie lustrzane ---
        self.mir_panel, lay = self._panel(312, 'Odbicie lustrzane', 'mirror', 'Obiekt → ściana-lustro', plain=True)
        self.mir_step1 = ui.StepRow(1, 'x_object', 'Obiekt do odbicia', plain=True)
        self.mir_step2 = ui.StepRow(2, 'x_wall', 'Ściana-lustro', plain=True)
        lay.addWidget(self.mir_step1)
        lay.addWidget(self.mir_step2)
        self.mir_keep = QCheckBox('Zachowaj oryginał (kopia)')
        self.mir_keep.setChecked(True)
        lay.addWidget(self.mir_keep)
        self.mir_join = QCheckBox('Połącz z oryginałem w jedną bryłę')
        lay.addWidget(self.mir_join)
        reset = QPushButton('Zmień obiekt')
        reset.clicked.connect(lambda _=False: self.reset_mirror())
        lay.addWidget(reset)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_mirror, lambda: self.set_mode(None))
        self.mir_keep.toggled.connect(lambda *_: self._timers['mirror'].start())
        self.mir_join.toggled.connect(lambda *_: self._timers['mirror'].start())

        # --- przetnij bryłę ---
        self.sp_panel, lay = self._panel(312, 'Przetnij bryłę', 'x_split', 'Podział bryły na części', plain=True)
        self.sp_step1 = ui.StepRow(1, 'x_object', 'Bryła do przecięcia', plain=True)
        lay.addWidget(self.sp_step1)
        self.sp_method = ui.Segmented([('Płaszczyzna', 'plane', 'sp_plane'), ('Ściana', 'face', 'sp_face'), ('Szkic', 'sketch', 'sp_sketch'), ('Bryła', 'body', 'sp_body')], 30)
        for b, tip in zip(self.sp_method._buttons, ('Płaszczyzna równoległa do XY, XZ albo YZ, przez środek bryły (z odsunięciem)',
                                                     'Płaszczyzna wskazanej płaskiej ściany (z odsunięciem)',
                                                     'Linia, łuk albo zamknięty profil szkicu - cięcie prostopadle do szkicu przez całą bryłę',
                                                     'Powierzchnia innej bryły - części wewnątrz i na zewnątrz niej')):
            b.setToolTip(tip)
        self._field(lay, 'Metoda', self.sp_method)
        self.sp_plane_box = QWidget()
        box = QVBoxLayout(self.sp_plane_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.sp_plane = ui.Segmented([('XY', 'XY', 'sp_xy'), ('XZ', 'XZ', 'sp_xz'), ('YZ', 'YZ', 'sp_yz')], 30)
        self._field(box, 'Płaszczyzna', self.sp_plane)
        lay.addWidget(self.sp_plane_box)
        self.sp_step2 = ui.StepRow(2, 'x_wall', 'Ściana cięcia', plain=True)
        lay.addWidget(self.sp_step2)
        self.sp_offset_box = QWidget()
        box = QVBoxLayout(self.sp_offset_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.sp_offset = _spin(0, -1e5, 1e5, 3, 1)
        self.sp_offset.setToolTip('Przesunięcie płaszczyzny cięcia wzdłuż strzałki; można też przeciągnąć strzałkę w widoku.')
        self._field(box, 'Odsunięcie (mm)', self.sp_offset)
        lay.addWidget(self.sp_offset_box)
        self.sp_keep = ui.Segmented([('Obie części', 'both', 'sp_both'), ('Zielona', '1', 'sp_side1'), ('Pomarańczowa', '2', 'sp_side2')], 30)
        for b, tip in zip(self.sp_keep._buttons, ('Obie części zostają jako osobne bryły', 'Zostaje tylko zielona część (z podglądu)', 'Zostaje tylko pomarańczowa część (z podglądu)')):
            b.setToolTip(tip)
        self._field(lay, 'Zostaw', self.sp_keep)
        self.sp_status = _label('', 'status')
        lay.addWidget(self.sp_status)
        reset = QPushButton('Zmień bryłę')
        reset.clicked.connect(lambda _=False: self.reset_split())
        lay.addWidget(reset)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_split, lambda: self.set_mode(None))
        self.sp_method.currentIndexChanged.connect(lambda *_: self._split_method_changed())
        self.sp_plane.currentIndexChanged.connect(lambda *_: self.update_split_status())
        self.sp_offset.valueChanged.connect(lambda *_: (self._place_split_handle(), self._timers['split'].start()))
        self.sp_keep.currentIndexChanged.connect(lambda *_: self._timers['split'].start())

        # --- dopasowanie i wyrównanie: ściana przesuwanej bryły względem ściany innej bryły ---
        self.mt_pick = {}
        self.mt_panels, self.mt_steps, self.mt_status = {}, {}, {}
        for key, title, sub, desc, second in (
                ('mate', 'Dopasowanie', 'Ściana do ściany', 'Pierwsza bryła obraca się i przesuwa tak, że jej wskazana ściana przylega do wskazanej ściany drugiej bryły, a środki obu ścian się spotykają.', 'Ściana docelowa'),
                ('align', 'Wyrównanie', 'Ściany na jednej wysokości', 'Pierwsza bryła przesuwa się bez obracania wzdłuż kierunku ściany wzorcowej, aż obie ściany leżą na tej samej wysokości - w każdej płaszczyźnie.', 'Ściana wzorcowa')):
            panel, lay = self._panel(312, title, 'x_' + key, sub, plain=True)
            panel.setToolTip(desc)
            steps = (ui.StepRow(1, 'x_wall', 'Ściana przesuwana', plain=True), ui.StepRow(2, 'x_wall', second, plain=True))
            for st in steps:
                lay.addWidget(st)
            if key == 'mate':
                # obrót przesuwanej bryły wokół osi prostopadłej do ścian, co 45° - animowane strzałki
                lay.addWidget(_label('Obrót wokół osi ścian', 'label'))
                spin_row = QHBoxLayout()
                spin_row.setSpacing(8)
                self.mt_left = ui.SpinArrow(1, 'w lewo 45°')
                self.mt_right = ui.SpinArrow(-1, 'w prawo 45°')
                self.mt_angle = QLabel('0°')
                self.mt_angle.setAlignment(Qt.AlignCenter)
                self.mt_angle.setStyleSheet('font-size:20px;font-weight:700;color:#1f3b57;')
                self.mt_left.clicked.connect(lambda _=False: self.spin_mate(45))
                self.mt_right.clicked.connect(lambda _=False: self.spin_mate(-45))
                spin_row.addWidget(self.mt_left)
                spin_row.addWidget(self.mt_angle, 1)
                spin_row.addWidget(self.mt_right)
                lay.addLayout(spin_row)
            status = _label('', 'status')
            lay.addWidget(status)
            again = QPushButton('Wskaż ściany od nowa')
            again.clicked.connect(lambda _=False: self._mt_reset())
            lay.addWidget(again)
            self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_mate, lambda: self.set_mode(None))
            self.mt_panels[key], self.mt_steps[key], self.mt_status[key] = panel, steps, status

        # --- szyk (prostokątny / kołowy / wzdłuż linii) ---
        self.pat_id, self.pat_path = None, None
        self.pat_picking = False
        self.pat_panel, lay = self._panel(312, 'Szyk', 'x_pattern', 'Prostokątny · kołowy · wzdłuż linii', plain=True, scroll=True)
        self.pat_step1 = ui.StepRow(1, 'x_object', 'Obiekt do szyku', plain=True)
        self.pat_step2 = ui.StepRow(2, 'x_pat_path', 'Ścieżka (linia lub krawędź)', plain=True)
        lay.addWidget(self.pat_step1)
        self.pat_filter = ui.Segmented([('Auto', 'auto', 'x_object'), ('Bryła', 'solid', 'x_extrude'), ('Szkic', 'sketch', 'x_area')], 20)
        for b, tip in zip(self.pat_filter._buttons, ('Bryła albo szkic - co jest pod kursorem', 'Tylko bryły', 'Tylko szkice')):
            b.setToolTip(tip)
        lay.addWidget(self.pat_filter)
        lay.addWidget(self.pat_step2)
        self.pat_kind = ui.Segmented([('Prostokątny', 'rect', 'x_pat_rect'), ('Kołowy', 'circ', 'x_pat_circ'), ('Wzdłuż linii', 'path', 'x_pat_path')], 30)
        lay.addWidget(self.pat_kind)
        # prostokątny: tabela oś | ilość | odstęp | kierunek (od obiektu wyjściowego)
        self.pat_rect = QWidget()
        grid = QGridLayout(self.pat_rect)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for col, text in ((1, 'Ilość'), (2, 'Odstęp (mm)'), (3, 'Kierunek')):
            grid.addWidget(_label(text), 0, col)
        self.pat_counts = [_spin(3 if i == 0 else 1, 1, 200, 0, 1) for i in range(3)]
        self.pat_gaps = [_spin(20, 0, 1e5, 2, 1) for _ in range(3)]
        self.pat_dirs = []
        self.pat_axis_pics = []
        arrows = (('←', '→', 'w lewo', 'w prawo'), ('↓', '↑', 'w tył (-Y)', 'w przód (+Y)'), ('↓', '↑', 'w dół', 'w górę'))
        for i, axis in enumerate('XYZ'):
            pic = QLabel()
            pic.setFixedSize(26, 26)
            pic.setPixmap(ui.icons.pixmap('tr_m' + axis.lower(), 26))
            pic.setToolTip(f'Oś {axis}')
            self.pat_axis_pics.append(pic)
            grid.addWidget(pic, i + 1, 0)
            self.pat_counts[i].setFixedWidth(52)
            grid.addWidget(self.pat_counts[i], i + 1, 1)
            grid.addWidget(self.pat_gaps[i], i + 1, 2)
            box = QHBoxLayout()
            box.setSpacing(3)
            pair = []
            for sign, (text, tip) in ((-1, (arrows[i][0], arrows[i][2])), (1, (arrows[i][1], arrows[i][3]))):
                b = QPushButton(text)
                b.setObjectName('dirchip')
                b.setCheckable(True)
                b.setChecked(sign > 0)
                b.setFixedSize(30, 30)
                b.setToolTip(f'Kopie {tip} od obiektu wyjściowego')
                b.sign = sign
                pair.append(b)
                box.addWidget(b)
            for b in pair:
                b.clicked.connect(lambda _=False, b=b, pair=pair: self._pattern_dir(pair, b))
            self.pat_dirs.append(pair)
            grid.addLayout(box, i + 1, 3)
        grid.setColumnStretch(2, 1)
        lay.addWidget(self.pat_rect)
        self.pat_circ = QWidget()
        cl = QVBoxLayout(self.pat_circ)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        self.pat_axis = ui.Segmented([('Oś Z', 'Z', 'tr_rz'), ('Oś X', 'X', 'tr_rx'), ('Oś Y', 'Y', 'tr_ry')], 26)
        self._field(cl, 'Oś obrotu', self.pat_axis)
        crow = QHBoxLayout()
        crow.setSpacing(8)
        d1, d2 = QVBoxLayout(), QVBoxLayout()
        self.pat_ccount = _spin(6, 1, 400, 0, 1)
        self.pat_angle = _spin(360, -360, 360, 1, 15)
        d1.addWidget(_label('Ilość'))
        d1.addWidget(self.pat_ccount)
        d2.addWidget(_label('Kąt całkowity (°)'))
        d2.addWidget(self.pat_angle)
        crow.addLayout(d1)
        crow.addLayout(d2)
        cl.addLayout(crow)
        cl.addWidget(_label('Środek obrotu (mm)'))
        prow = QHBoxLayout()
        prow.setSpacing(6)
        self.pat_pivot = [_spin(0, -1e6, 1e6, 2, 1) for _ in range(3)]
        for axis, spin in zip('XYZ', self.pat_pivot):
            col = QVBoxLayout()
            col.addWidget(_label(axis))
            col.addWidget(spin)
            prow.addLayout(col)
        cl.addLayout(prow)
        self.pat_pick = QPushButton('Wskaż środek na modelu')
        self.pat_pick.setCheckable(True)
        self.pat_pick.toggled.connect(lambda on: self._pattern_pick_toggled(on))
        cl.addWidget(self.pat_pick)
        self.pat_radius = _spin(0, 0, 1e6, 2, 1)
        self._field(cl, 'Odległość obiektu od środka (mm)', self.pat_radius)
        lay.addWidget(self.pat_circ)
        self.pat_line = QWidget()
        ll = QVBoxLayout(self.pat_line)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        lrow = QHBoxLayout()
        lrow.setSpacing(8)
        e1, e2 = QVBoxLayout(), QVBoxLayout()
        self.pat_lcount = _spin(5, 1, 400, 0, 1)
        self.pat_lgap = _spin(20, .01, 1e5, 2, 1)
        e1.addWidget(_label('Ilość'))
        e1.addWidget(self.pat_lcount)
        e2.addWidget(_label('Odstęp (mm)'))
        e2.addWidget(self.pat_lgap)
        lrow.addLayout(e1)
        lrow.addLayout(e2)
        ll.addLayout(lrow)
        self.pat_fit = QCheckBox('Rozmieść równo na całej długości')
        self.pat_fit.setChecked(True)
        ll.addWidget(self.pat_fit)
        lay.addWidget(self.pat_line)
        # wynik: kopie osobno / połączone w jedną bryłę / jako jeden element (grupa)
        self.pat_result = ui.Segmented([('Osobno', 'separate', 'x_pat_separate'), ('Jeden element', 'group', 'x_pat_group'), ('Jedna bryła', 'join', 'x_pat_join')], 30)
        for b, tip in zip(self.pat_result._buttons, ('Każda kopia jest osobnym obiektem',
                                                     'Kopie i oryginał zachowują się jak jeden element: kliknięcie zaznacza wszystkie, wyciągnięcie / wycięcie '
                                                     'szkicu działa na wszystkie, przesuwanie i obracanie przenosi je razem',
                                                     'Bryły: kopie łączą się z oryginałem w jedną bryłę')):
            b.setToolTip(tip)
        self._field(lay, 'Wynik', self.pat_result)
        self.pat_join = QCheckBox()           # zgodność: stan „Jedna bryła” (używany w testach i przepisach)
        self.pat_join.hide()
        self.pat_join.toggled.connect(lambda on: self.pat_result.setCurrentIndex(2 if on else (0 if self.pat_result.currentData() == 'join' else self.pat_result.currentIndex())))
        self.pat_result.currentIndexChanged.connect(lambda *_: self.pat_join.setChecked(self.pat_result.currentData() == 'join'))
        self.pat_status = _label('', 'status')
        lay.addWidget(self.pat_status)
        footer = self.pat_panel.footer
        self._buttons(footer, 'Zastosuj (Enter)', 'Zamknij', self.apply_pattern, lambda: self.set_mode(None))
        reset = QPushButton('Zmień obiekt')
        reset.clicked.connect(lambda _=False: self.reset_pattern())
        footer.addWidget(reset)
        for spin in (*self.pat_gaps, self.pat_ccount, self.pat_angle, *self.pat_pivot, self.pat_lcount, self.pat_lgap, self.pat_radius):
            spin.setMinimumWidth(40)          # pola mieszczą się w panelu (bez wystawania pod pasek przewijania)
        self.pat_kind.currentIndexChanged.connect(lambda *_: self._pattern_kind_changed())
        for w in (*self.pat_counts, *self.pat_gaps, self.pat_ccount, self.pat_angle, self.pat_lcount, self.pat_lgap, self.pat_radius):
            w.valueChanged.connect(lambda *_: self._timers['pattern'].start())
        for w in self.pat_pivot:
            w.valueChanged.connect(lambda *_: self._pattern_pivot_changed())
        self.pat_axis.currentIndexChanged.connect(lambda *_: self._pattern_pivot_changed())
        for w in (self.pat_fit, self.pat_join):
            w.toggled.connect(lambda *_: self._timers['pattern'].start())

        # --- tekst: powierzchnia -> obszar -> treść (jak kreator odbicia lustrzanego) ---
        self.txt = None
        self._text_ext = {}
        self.text_panel, lay = self._panel(320, 'Tekst', 'x_text', 'Powierzchnia → obszar → treść', plain=True, scroll=True)
        self.txt_step1 = ui.StepRow(1, 'x_surface', 'Powierzchnia', plain=True)
        self.txt_step2 = ui.StepRow(2, 'x_area', 'Obszar napisu', plain=True)
        lay.addWidget(self.txt_step1)
        lay.addWidget(self.txt_step2)
        self.text_form = QWidget()
        form = QVBoxLayout(self.text_form)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(9)
        form.addWidget(ui.StepRow(3, 'x_text', 'Treść', plain=True))
        self.text_edit = QLineEdit('Tekst')
        self.text_edit.setObjectName('textInput')
        self.text_edit.setPlaceholderText('Wpisz napis…')
        form.addWidget(self.text_edit)
        # podgląd napisu w wybranej czcionce i stylu
        self.text_sample = QLabel()
        self.text_sample.setObjectName('textSample')
        self.text_sample.setAlignment(Qt.AlignCenter)
        self.text_sample.setFixedHeight(64)
        self.text_sample.setToolTip('Tak będzie wyglądał napis (czcionka i styl)')
        form.addWidget(self.text_sample)
        self.text_font = QFontComboBox()
        self.text_font.setEditable(False)
        self.text_font.setFontFilters(QFontComboBox.ScalableFonts)
        self.text_font.setMaxVisibleItems(18)
        for name in ('Arial', 'Segoe UI', 'Calibri', 'DejaVu Sans'):
            if name in QFontDatabase.families():
                self.text_font.setCurrentFont(QFont(name))
                break
        self._field(form, 'Czcionka', self.text_font)
        style_row = QHBoxLayout()
        style_row.setSpacing(8)
        self.text_bold, self.text_italic, self.text_caps = (QPushButton(t) for t in ('B', 'I', 'AA'))
        for chip, tip in ((self.text_bold, 'Pogrubienie'), (self.text_italic, 'Pochylenie'), (self.text_caps, 'WERSALIKI')):
            chip.setObjectName('chip')
            chip.setCheckable(True)
            chip.setToolTip(tip)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setMinimumWidth(56)
            style_row.addWidget(chip, 1)
        self.text_bold.setStyleSheet('font-weight:900;')
        self.text_italic.setStyleSheet('font-style:italic;font-family:serif;')
        form.addWidget(_label('Styl'))
        form.addLayout(style_row)
        self.text_size = _spin(10, .1, 5000, 2, 1)
        self.text_angle = _spin(0, -360, 360, 1, 5)
        self._pic_field(form, 'Wysokość liter (mm)', 'tx_size', self.text_size, 'Wysokość wielkiej litery; niebieski uchwyt ramki w widoku też ją zmienia.')
        self._pic_field(form, 'Obrót (°)', 'tx_angle', self.text_angle, 'Obrót napisu w płaszczyźnie; czerwony punkt ramki w widoku też obraca.')
        lay.addWidget(self.text_form)
        self.text_status = _label('', 'status')
        lay.addWidget(self.text_status)
        footer = self.text_panel.footer
        self._buttons(footer, 'Zatwierdź (Enter)', 'Zamknij', self.apply_text, self.text_cancel)
        again = QPushButton('Zmień powierzchnię')
        again.clicked.connect(lambda _=False: self._text_set_stage('surface'))
        footer.addWidget(again)
        self.text_form.setEnabled(False)
        for sig in (self.text_edit.textChanged, self.text_font.currentIndexChanged, self.text_bold.toggled, self.text_italic.toggled,
                    self.text_caps.toggled):
            sig.connect(lambda *_: (self._text_sample_update(), self._text_refresh()))
        self.text_size.valueChanged.connect(lambda *_: self._text_spin_changed())
        self.text_angle.valueChanged.connect(lambda *_: self._text_spin_changed())
        self._text_sample_update()

        # --- ofset szkicu ---
        self.off = None             # wybrany kształt: dict(body, base, dir)
        self.off_panel, lay = self._panel(286, 'Ofset', 'x_offset', 'Kształt → strona → odległość', plain=True)
        self.off_step = ui.StepRow(1, 'x_area', 'Kształt szkicu', plain=True)
        lay.addWidget(self.off_step)
        self.off_side = ui.Segmented([('Na zewnątrz', 'out', 'sh_out'), ('Do wewnątrz', 'in', 'sh_in')], 30)
        self._field(lay, 'Strona', self.off_side)
        self.off_value = _spin(2, .01, 1e5, 2, .5)
        self.off_value_pic = self._pic_field(lay, 'Odległość (mm)', 'of_dist', self.off_value, 'Odstęp nowego kształtu od wskazanego; strzałkę przy kształcie można też przeciągać.')
        self.off_status = _label('Kliknij kształt szkicu.', 'status')
        lay.addWidget(self.off_status)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_offset, lambda: self.choose_tool(None))
        self.off_side.currentIndexChanged.connect(lambda *_: self._off_update())
        self.off_value.valueChanged.connect(lambda *_: self._off_update())

        self._build_ply_panels()
        self._build_scale_panel()
        self._build_section()
        self.panels = (*self.ply_panels(), self.scale_panel, *self.ms_panels.values(), *self.dr_panels.values(), self.ex_panel, self.ex_bar, self.rev_panel, self.sweep_panel, self.loft_panel, self.shell_panel, self.thread_panel, self.sheet_panel, self.flange_panel, self.hem_panel, self.rules_panel, self.bool_panel, self.mod_panel, self.sp_panel, self.mir_panel, self.pat_panel, self.text_panel, self.off_panel, *self.mt_panels.values())
        for p in self.panels:
            p.adjustSize()

    def _layout_overlays(self):
        W, H = self.view.width(), self.view.height()
        x = 18
        for name, tab in self.tab_buttons.items():
            tab.adjustSize()
            tab.setFixedHeight(28)
            tab.move(x, TAB_TOP)
            x += tab.width() + 6
        self.tools['file'].move(18, TOOLS_TOP)
        shown = self._tab_tools(self._tab)
        for key in TAB_OF:
            self.tools[key].setVisible(key in shown)
        self._update_surface_button()
        for i, key in enumerate(shown):
            self.tools[key].move(78 + 60 * i, TOOLS_TOP)
        self.shape_bar.move(18, 80 + TOOLS_TOP - 18)
        # Fit the extra section button between tabs and the view cube. On narrow
        # windows the compact row goes below the tabs, keeping every tool reachable.
        ratio=min(1.0,max(.75,(W-205-x-12)/337))
        controls_y=20 if W-205-337*ratio>=x+4 else 64
        size=40 if ratio==1 else max(32,int(48*ratio)-4)
        controls=((self.clear_button,542),(self.undo_button,494),(self.redo_button,446),
                  (self.section_button,398),(self.scale_button,350),(self.layers,302),(self.xray,254),(self.home,205))
        for button,offset in controls:
            button.setFixedSize(size,size)
            button.move(round(W-205-(offset-205)*ratio),controls_y)
        self.section_panel.adjustSize();self.section_panel.move(max(340,W-650),max(68,controls_y+48))
        self.section_panel.raise_()
        self.cube.move(W - 160, 20)
        self.busy_bar.move(W - 160 + (138 - self.busy_bar.width()) // 2, 164)
        self.objects.relayout()
        self.objects.move(W - (18 if self.objects.open else 0) - self.objects.width(), 212)   # zwinięta lista: pasek przy samej krawędzi
        self.pad.adjustSize()
        self.pad.move((W - self.pad.width()) // 2, H - 113 - self.pad.height())
        self.t_editor.adjustSize()
        self.t_editor.move(18, 88 + TOOLS_TOP - 18)
        self.hist_bar.setFixedWidth(max(300, min(W - 460, 1100)))
        self.hist_bar.adjustSize()
        self.hist_bar.move((W - self.hist_bar.width()) // 2, H - 18 - self.hist_bar.height())
        self.sk_bar.adjustSize()
        self.sk_bar.move(max(560, (W - self.sk_bar.width()) // 2), 18)
        self.origin_label.adjustSize()
        self.origin_label.move(W - 18 - self.origin_label.width(), H - 15 - self.origin_label.height())
        self.notice.adjustSize()
        self.notice.move(W - 18 - self.notice.width(), H - 22 - self.notice.height())
        for p in (self.bool_panel, self.mod_panel, self.sp_panel, self.mir_panel, self.pat_panel, self.rev_panel, self.shell_panel, self.thread_panel, self.sheet_panel, self.flange_panel, self.hem_panel, self.rules_panel, self.sweep_panel, self.loft_panel, *self.ms_panels.values(), *self.mt_panels.values(), *self.ply_panels(), self.scale_panel):
            self._fit_panel(p, 88 + TOOLS_TOP - 18)
            p.move(18, 88 + TOOLS_TOP - 18)
        self._fit_panel(self.text_panel, 88 + TOOLS_TOP - 18)
        self.text_panel.move(92, 88 + TOOLS_TOP - 18)
        self.off_panel.adjustSize()
        self.off_panel.move(92, 88 + TOOLS_TOP - 18)
        self.ex_panel.adjustSize()
        self.ex_panel.move(18, 170 + TOOLS_TOP - 18)
        self.ex_bar.adjustSize()
        self.ex_bar.move(346, 170 + TOOLS_TOP - 18)
        for w in (*self.tools.values(), *self.tab_buttons.values(), self.shape_bar, self.clear_button, self.undo_button, self.redo_button, self.section_button, self.scale_button, self.layers, self.xray, self.home, self.cube, self.objects, self.pad, self.hist_bar, self.hist_edit, self.hist_vars,
                  self.t_editor, self.sk_bar, self.origin_label, *self.panels, self.dim_panel, self.dim, self.notice):
            w.raise_()

    def eventFilter(self, obj, event):
        if not hasattr(self, '_dim_target'):
            return super().eventFilter(obj, event)
        if obj is self.dim_panel and event.type() == QEvent.Hide and self._dim_target is not None:
            self._dim_target = None
            self.view.set_preview_mesh(None)
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Tab and self.isActiveWindow() and not self.busy and not isinstance(QApplication.focusWidget(), QPlainTextEdit):
            if self.dim_panel.isVisible():
                edits = [e for e in self.dim_edits if e.isVisible()]
                if len(edits) > 1:
                    index = next((i for i, e in enumerate(edits) if e.hasFocus()), -1)
                    edits[(index + 1) % len(edits)].setFocus()
                    edits[(index + 1) % len(edits)].selectAll()
                return True
            if self.mode == 'sketch' and self.points and self.open_dim_input():
                return True
            if self.mode in (None, 'sketch') and not self.points and not self.tangent_lines and self.tool not in ('trim',):
                if self.mode is None and not self.selected and self._sketch_edit_target() is None:
                    return super().eventFilter(obj, event)
                if self.open_dim_edit():
                    return True
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.isActiveWindow() and not self.busy:
            action = {'extrude': self.apply_extrude, 'revolve': self.apply_revolve, 'shell': self.apply_shell, 'sweep': self.apply_sweep, 'loft': self.apply_loft, 'bool': self.apply_bool, 'mod': self.apply_mod, 'split': self.apply_split, 'mirror': self.apply_mirror, 'pattern': self.apply_pattern,
                      'move': self.apply_transform, 'rotate': self.apply_transform, 'mate': self.apply_mate, 'align': self.apply_mate, 'scale': self.apply_scale,
                      'ply': self.apply_ply_panel, 'ply_wall': self.apply_ply_wall, 'ply_between': self.apply_ply_between, 'ply_joints': self.apply_ply_joints}.get(self.mode)
            if action is None and self.mode == 'sketch' and self.tool == 'text' and self.txt and self.txt['stage'] == 'edit':
                action = self.apply_text
            focus = QApplication.focusWidget()
            if action and not isinstance(focus, QPlainTextEdit) and (focus is None or self.isAncestorOf(focus) or focus is self):
                action()
                return True
        if obj is self.view and event.type() == QEvent.Resize:
            self._layout_overlays()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_overlays()

    # =====================================================================
    # komunikaty
    # =====================================================================
    def hint(self, text):
        pass  # podpowiedzi przeniesione do samouczka (Plik → Pomoc)

    def toast(self, text, ms=4500):
        self.notice.setText(text)
        self.notice.adjustSize()
        self.notice.show()
        self._layout_overlays()
        self.notice_timer.start(ms)

    def set_origin_text(self, text=None):
        self.origin_label.setText(text or 'Płaszczyzny XY · XZ · YZ')
        self._layout_overlays()

    # =====================================================================
    # widok: kostka, płaszczyzny
    # =====================================================================
    def _mark_view(self, name):
        pass

    CUBE_PLANES = {'Z': 'XY', '-Z': 'XY', 'X': 'YZ', '-X': 'YZ', 'Y': 'XZ', '-Y': 'XZ'}

    def _cube_clicked(self, name):
        plane = self.CUBE_PLANES.get(name)
        if plane is not None and not self.busy and self.mode == 'sketch' and self.tool == 'text' and self.txt and self.txt['stage'] == 'surface':
            self._text_plane_keep = True       # tekst: ściana kostki = kliknięcie płaszczyzny na polu roboczym
            self.enter_sketch(plane)
            self.view.set_view(name)
            self._cube_pick = (name, plane)
            return
        if plane is not None and not self.busy and self.mode in ('plane', 'sketch'):
            # ściana kostki wybiera płaszczyznę szkicu dokładnie tak jak kliknięcie płaszczyzny na polu roboczym
            self.enter_sketch(plane)
            self.view.set_view(name)
            self._cube_pick = (name, plane)
            self._mark_view(name)
            return
        self.view.set_view(name)
        self._cube_pick = (name, plane) if plane is not None else None
        self._mark_view(name)

    def _cube_plane_if_current(self):
        """Płaszczyzna wybrana ścianą kostki, dopóki kamera nadal na nią patrzy - wtedy szkic startuje od razu, bez ponownego wyboru."""
        pick = getattr(self, '_cube_pick', None)
        if not pick:
            return None
        el, az = VIEWS_FOR_CUBE[pick[0]]
        d_az = (float(self.view.opts['azimuth']) - az + 180.0) % 360.0 - 180.0
        if abs(float(self.view.opts['elevation']) - el) < 1.0 and abs(d_az) < 1.0:
            return pick[1]
        return None

    def _planes_toggled(self, on):
        self._planes_visible = on
        if self.mode != 'plane':
            self.view.show_planes(on)

    def _xray_toggled(self, on):
        self.view.set_xray(on)

    def _camera_changed(self):
        """Uchwyty przesuwania / obrotu skalują się z odległością kamery, żeby były zawsze wygodne do złapania."""
        if self.mode in ('move', 'rotate') and self.t_target is not None and self._hv is None and not self.view._handle_drag:
            if not self._timers['gizmo'].isActive():
                self._timers['gizmo'].start()

    # =====================================================================
    # tryby
    # =====================================================================
    def toggle_mode(self, key):
        if self.busy:
            return
        target = 'plane' if key == 'sketch' else key
        current = 'plane' if self.mode == 'sketch' else self.mode
        if current == target:
            self.set_mode(None)
            return
        self.set_mode(target)
        chosen = self._cube_plane_if_current() if target == 'plane' else None
        if chosen is not None:
            self.enter_sketch(chosen)      # powierzchnia już wybrana na kostce: bez ponownego wskazywania

    def set_mode(self, mode):
        """Przełącza narzędzie; None = zwykłe zaznaczanie."""
        if self.busy:
            return
        self._sh_xray(False)
        self._result_preview = False
        self.override = {}
        self.txt = None
        self._mod_face_mesh = None
        self.mod_vertices = {}
        self.view.sel_vertices = []
        self.view.hover_vertex = None
        self.view.sketch_box = None
        self.view.clear_body_matrices()
        self.cancel_previews()
        self.view.snapper = None
        self.view.hover_gate = None
        self.view.free_drag = None
        self.mode = mode
        self.points = []
        self.tangent_lines = []
        self._hv = None
        self.dim.hide()
        self.dim_panel.hide()
        self.view.set_preview_mesh(None)
        self.view.set_selection_meshes(None)
        self.view.drag_hook = None
        self.view.sketch_grips = []
        self.view.set_handles([])
        self.view.set_thread_preview(None)      # podgląd gwintu nie zostaje po wyjściu z narzędzia
        self.view._set_hover_edge(None)
        self._sp_hover = None
        self.view.set_marker(None)
        self.view.sketch_plane = None
        self.view.sketch_tool = None
        self.view.plane_pick = False
        self.view.edge_mode = False
        self.view.tints = {}
        self.view.show_custom_plane(None)
        self.view.set_grid_frame(None)
        self.sketch_plane = None
        self.ex_profiles = []
        self._ex_pick_order=[];self._mod_pick_order=[]
        self.ex_target = None
        self._ex_join_scope_update()
        if hasattr(self, 'ex_target_label'):
            self.ex_target_label.hide()
        self.rev_profiles,self.rev_line, self._rev_manual = [], None, False
        self.sh_id, self.sh_faces = None, []
        self.sw_profiles, self.sw_path, self.lf_profiles, self.lf_point = [], None, [], None
        self.ms_points = []
        self.view.measure_labels=[];self.view.measure_live=None
        self.bool_ids = []
        self.mirror_id = None
        self.mirror_frame = None
        self.sp_id, self.sp_ref = None, None
        self.mt_pick = {}
        self.off = None
        self.mt_spin = 0.0
        if hasattr(self, 'mt_angle'):
            self.mt_angle.setText('0°')
        self.pat_id, self.pat_path = None, None
        self.mod_vertices = {}
        self.t_target = None
        self.t_group = []
        self.edges = {}
        self._hover_key = None
        if hasattr(self, 'scale_button'):
            self.scale_button.setChecked(mode == 'scale')
        for key, button in self.tools.items():
            if key != 'file':
                button.setChecked(key == ('sketch' if mode == 'plane' else mode))
        for key, button in self.pad_buttons.items():
            button.setChecked(key == mode)
        key = 'sketch' if mode in ('plane', 'sketch') else mode
        tab = TAB_OF.get(key)
        if tab and not (self._tab == 'Ulubione' and key in self.favorites):     # narzędzie z Ulubionych zostaje w Ulubionych
            self.set_tab(tab)
        for p in (self.shape_bar, self.t_editor, self.sk_bar, *self.panels):
            p.hide()
        self._update_surface_button()
        self.view.show_planes(self._planes_visible)
        self.view.setCursor(Qt.ArrowCursor)
        self.set_origin_text()
        if mode == 'plane':
            self.view.plane_pick = True
            self.view.show_planes(True)
            self.view.setCursor(Qt.PointingHandCursor)
            self.shape_bar.show()
            self.hint('Wybierz płaszczyznę XY, XZ lub YZ albo kliknij ścianę bryły, aby rozpocząć szkic.')
        elif mode == 'extrude':
            self.ex_panel.show()
            self.ex_status.setText('Kliknij zamknięty profil szkicu lub płaską ścianę bryły.')
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Wyciągnięcie: kliknij profil szkicu lub ścianę bryły.')
            if self.selected:
                profiles = self._selected_sketch_profiles()     # zaznaczone szkice (np. cała grupa DXF / SVG) - od razu wybrane
                if profiles:
                    self.ex_profiles = profiles
                    self._ex_profiles_changed()
                    self.toast(f'Wybrano profili z zaznaczonych szkiców: {len(profiles)}. Shift + klik odznacza te, które nie mają być wyciągnięte.', 5000)
        elif mode == 'revolve':
            self.rev_panel.show()
            self._rev_update()
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Obrót: kliknij profil szkicu lub ścianę bryły, potem wybierz oś.')
        elif mode in MEASURE_MODES:
            self.ms_panels[mode].show()
            self._measure_reset()
            self.view.setCursor(Qt.CrossCursor)
            self.hint({'mdist': 'Odległość: kliknij pierwszy punkt.', 'mangle': 'Kąt: kliknij pierwszy punkt ramienia.',
                       'mrad': 'Kliknij okrągłą krawędź lub łuk.', 'mprops': 'Kliknij bryłę albo szkic.'}[mode])
        elif mode in DRAWING_MODES:
            self.dr_panels[mode].show()
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Rysunek techniczny: kliknij bryłę, z której ma powstać rysunek.')
        elif mode == 'sheet':
            self.sheet_panel.show()
            self.sheet_pick = None
            self.view.set_selection_meshes(None)
            self.sheet_t.setText('—')
            self.sheet_dims.setText('—')
            self.sheet_status.setText('Kliknij płaską prostokątną ścianę bryły.')
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Konwersja na blachę: kliknij płaską ścianę prostopadłościanu.')
        elif mode == 'rules':
            bodies = [b for b in self.document.bodies if b.id in self.selected]
            state = self._sheet_state(bodies[0].id) if len(bodies)==1 else None
            if state is not None:
                rules = state['rules']
                self.fl_joint.setCurrentIndex(self.fl_joint.findData(('sheet' if rules.get('joint') == 'diagonal' else rules.get('joint','parallel'))))
                self.fl_gap.setValue(float(rules.get('gap',0)))
                self.fl_relief.setCurrentIndex(self.fl_relief.findData(rules.get('relief','none')))
                self.fl_relief_size.setValue(float(rules.get('relief_size',3)))
                self.fl_kfactor.setValue(float(rules.get('kfactor',shm.K_DEFAULT)))
                self.fl_outside.setChecked(bool(rules.get('outside',False)))
            self.rl_pick = False
            self.rl_status.setText('Ustawienia wzięte z zaznaczonej blachy.' if state is not None else 'Zaznacz blachę albo kliknij „Zastosuj do blachy” i wskaż ją.')
            self.rules_panel.show()
            self.view.setCursor(Qt.ArrowCursor)
            self.hint('Reguły blach: szczelina i wycięcia w narożnikach dla nowych kołnierzy.')
        elif mode == 'flange':
            self.flange_panel.show()
            self.fl_armed = False
            self._style_bend_button()
            self.fl_pick = None
            self.view.set_picked_edge(None)
            self.fl_status.setText('Kliknij Zaginaj, potem klikaj krawędzie blachy.')
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Kołnierz: kliknij krawędź blachy (górna w górę, dolna w dół).')
        elif mode == 'hem':
            self.hem_panel.show()
            self.fl_armed = False
            self._style_bend_button()
            self.fl_pick = None
            self.view.set_picked_edge(None)
            self.hm_status.setText('Kliknij Zaginaj, potem klikaj krawędzie blachy.')
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Zawinięcie: kliknij krawędź blachy. Krawędź zawija się do środka o 180°.')
        elif mode in PLY_MODES:
            self._ply_enter(mode)
        elif mode == 'tabwall':
            self._tw_enter()
        elif mode == 'scale':
            self._scale_enter()
        elif mode == 'thread':
            self.thread_panel.show()
            self.th_pick = None
            self.th_extra = []
            self._th_update()
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Gwint: kliknij otwór albo wałek. Strzałki w widoku ustawiają długość i rozmiar; gwint powstaje po Zastosuj.')
        elif mode == 'shell':
            self.shell_panel.show()
            solids = [i for i in self.selected if (b := self.document.get(i)) is not None and b.kind == 'solid']
            if solids and self.sh_id is None:
                self.sh_id, self.sh_faces = solids[0], []        # bryła (bryły) zaznaczone przed włączeniem narzędzia
            self._sh_update()
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Skorupa: kliknij bryłę, potem ściany, które mają zostać otwarte.')
        elif mode == 'sweep':
            self.sweep_panel.show()
            self._sw_update()
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Przeciągnięcie: kliknij profil, potem ścieżkę (linię, łuk szkicu albo krawędź bryły).')
        elif mode == 'loft':
            self.loft_panel.show()
            self._lf_update()
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Wyciągnięcie złożone: kliknij kolejne profile (w kolejności przejścia).')
        elif mode == 'bool':
            self.bool_panel.show()
            self.update_bool_status()
            self.hint('Boolean: kliknij bryłę bazową, potem bryły-narzędzia.')
        elif mode == 'mod':
            self.mod_panel.show()
            self.view.edge_mode = True
            self.mod_size.blockSignals(True)
            self.mod_size.setValue(2.0)
            self.mod_size.blockSignals(False)
            self._mod_kind_changed()
            self.update_mod_status()
            self.hint('Edytuj bryłę: klikaj krawędzie i narożniki - każde kliknięcie dodaje kolejne, Shift + klik odznacza.')
        elif mode in ('mate', 'align'):
            self.mt_panels[mode].show()
            self.view.setCursor(Qt.PointingHandCursor)
            self._mt_update()
        elif mode == 'split':
            self.sp_panel.show()
            self.view.setCursor(Qt.PointingHandCursor)
            chosen = next((b for b in (self.document.get(i) for i in self.selected) if b is not None and b.kind == 'solid'), None)
            if chosen is not None:
                self.sp_id = chosen.id                      # bryła (bryły) zaznaczone przed włączeniem narzędzia
            self._split_method_changed()
            self.hint('Przetnij bryłę: kliknij bryłę, wybierz metodę i wskaż, czym ją przeciąć.')
        elif mode == 'mirror':
            self.mir_panel.show()
            chosen = next((b for b in (self.document.get(i) for i in self.selected) if b is not None and b.kind in ('solid', 'sketch')), None)
            if chosen is not None and self.mirror_id is None:
                self.mirror_id = chosen.id                  # zaznaczone wcześniej: od razu krok 2 (płaszczyzna odbicia)
                self._tint_targets(chosen.id, ('solid', 'sketch'))
            self.update_mirror_status()
            self.hint('Lustro: kliknij bryłę, a potem ścianę, względem której ma nastąpić odbicie.')
        elif mode == 'pattern':
            self.pat_panel.show()
            self._pattern_kind_changed()
            self.update_pattern_status()
            self.hint('Szyk: kliknij bryłę lub szkic, ustaw rodzaj i parametry.')
        elif mode in ('move', 'rotate'):
            self.t_editor.show()
            self.t_status.setText('Kliknij obiekt, aby go zaznaczyć')
            for key, head in self.t_heads.items():
                head.setVisible(key == mode)
            for label, pic, axis in zip(self.t_axis_labels, self.t_axis_pics, 'XYZ'):
                label.setText(f'{axis} (°)' if mode == 'rotate' else f'{axis} (mm)')
                pic.setPixmap(ui.icons.pixmap(('tr_r' if mode == 'rotate' else 'tr_m') + axis.lower(), 40))
            self.t_editor.adjustSize()
            for spin in self.t_spins:
                spin.blockSignals(True)
                spin.setValue(0)
                spin.blockSignals(False)
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Kliknij bryłę lub szkic, który chcesz ' + ('przesunąć.' if mode == 'move' else 'obrócić.'))
            if self.selected:
                body = self.document.get(self.selected[-1])
                if body is not None:
                    self.select_transform_target(body)
        self.refresh()
        self._layout_overlays()

    # =====================================================================
    # szkic
    # =====================================================================
    def _tool_clicked(self, name):
        """Ponowne kliknięcie aktywnego narzędzia wyłącza je (zostaje sam szkic: zaznaczanie i skalowanie kształtów)."""
        if self.tool is not None and (self.tool == name or self._group_button(self.tool) == name):
            self.choose_tool(None)
        else:
            self.choose_tool(name)

    def choose_tool(self, name, button=None):
        if name is not None and self.mode == 'sketch' and self.selected:
            self.selected = []
            self.refresh()
        self.tool = name
        self.points = []
        self.tangent_lines = []
        self.text_panel.setVisible(name == 'text')
        self.off_panel.setVisible(name == 'offset' and self.mode == 'sketch')
        self._off_clear()
        if name == 'text':
            self._text_begin()
        else:
            self._text_end()
        self.dim.hide()
        self.dim_panel.hide()
        self.view.set_preview_mesh(None)
        self.view.sketch_tool = name
        main = button or self.shape_buttons.get(self._group_button(name))
        for b in self.shape_buttons.values():
            b.setChecked(b is main)
        if self.mode == 'sketch':
            self.show_sketch_hint()
            self.sk_hint.setText('Wybierz kształt do rysowania' if name is None and not self.selected else
                                 ('Tab – wymiary · przeciągnij krawędź – skaluj' if name is None else 'Rysuj na płaszczyźnie; Esc kończy kształt'))
        self._update_grips()
        self._layout_overlays()

    @staticmethod
    def _group_button(name):
        return {'centerRect': 'rect', 'rect3': 'rect', 'circle2': 'circle', 'circle3': 'circle', 'circleTangent2': 'circle'}.get(name, name)

    def show_sketch_hint(self):
        texts = HINTS.get(self.tool, [''])
        self.hint(texts[min(len(self.points) + len(self.tangent_lines), len(texts) - 1)])

    def _plane_label(self):
        return self.sketch_plane if isinstance(self.sketch_plane, str) else 'ściana'

    def pick_surface(self, x, y, announce=False):
        """Płaszczyzna szkicu spod kursora: płaska ściana bryły (Frame) albo jedna z płaszczyzn XY / XZ / YZ."""
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is not None and body.kind == 'solid':
            try:
                face, normal = self.view.face_at(body,hit, curved=True)
                if kernel.is_planar_face(face):
                    return kernel.face_frame(face.Center().toTuple(), normal), face
                origin, fit = kernel.supporting_plane(face, hit[2], normal)
                if announce:
                    self.toast('Ściana jest skręcona (nie płaska): szkic leży na płaszczyźnie przylegającej do niej od zewnątrz, a głębokość wycięcia liczy się od tej płaszczyzny.', 7000)
                return kernel.face_frame(origin, fit), face
            except kernel.CadError:
                return None, None
        return self.view.plane_at(x, y), None

    def enter_sketch(self, plane):
        self.mode = 'sketch'
        self.sketch_plane = plane
        self.view.plane_pick = False
        self.view.sketch_plane = plane
        self.view.snapper = self._snapper
        self.view.hover_gate = self.sketch_hover_wanted
        self.view.drag_hook = self._sketch_hook
        self._sk_drag = None
        self.view.show_planes(False)
        self.layers.blockSignals(True)
        self.layers.setChecked(False)
        self.layers.blockSignals(False)
        self._planes_visible = False
        self.view.set_preview_mesh(None)
        self.view.look_along(plane)
        self.view.set_grid_frame(plane)
        self._mark_view(None)
        self.view.setCursor(Qt.ArrowCursor)
        self.points = []
        self.shape_bar.show()
        self._update_surface_button()
        self.sk_title.setText(f'Szkic · płaszczyzna {self._plane_label()}')
        self.sk_hint.setText('Rysuj na płaszczyźnie; Esc kończy kształt')
        self.set_origin_text(f'Szkic · płaszczyzna {self._plane_label()}')
        self.choose_tool(self.tool)

    def _update_surface_button(self):
        """Przycisk „Inna powierzchnia” obok Szkicu widać tylko w trakcie szkicowania."""
        button = self.tools.get('surface')
        if button is not None:
            button.setVisible('surface' in self._tab_tools(self._tab) and self.mode == 'sketch')

    def pick_other_surface(self):
        """Z trybu szkicu wraca do wskazywania powierzchni, bez wychodzenia z szkicowania i ponownego włączania narzędzia."""
        if self.busy or self.mode != 'sketch':
            return
        self.set_mode('plane')

    def plane_picked(self, name):
        self.enter_sketch(name)

    def _snapper(self, x, y, raw):
        """Przyciąganie w szkicu z opóźnieniem: kursor jest wolny w ruchu, a do punktu (narożnik kratki siatki, punkt szkicu, krawędź
        lub narożnik ścianki) przykleja się dopiero, gdy chwilę przy nim zostanie. Timer odświeża wtedy podgląd bez ruchu myszy."""
        key = (self.sketch_plane if isinstance(self.sketch_plane, str) else id(self.sketch_plane),
               tuple((b.id, id(b.mesh), b.visible) for b in self.document.bodies if b.kind in ('sketch', 'solid')))
        if self._snap_cache is None or self._snap_cache[0] != key:
            self._snap_cache = (key, snapping.SketchGeometry(self.document.bodies, self.sketch_plane))
        if getattr(self, '_dwell', None) is None:
            self._dwell = snapping.Dwell()
            self._dwell_timer = QTimer(self)
            self._dwell_timer.setSingleShot(True)
            self._dwell_timer.timeout.connect(self._dwell_refresh)
        c = snapping.candidate(self.view, self._snap_cache[1], x, y, raw)
        point, wait = self._dwell.update(c, x, y)
        if wait:
            self._dwell_timer.start(int(self._dwell.delay_for(c) * 1000) + 15)
        return point if point is not None else (float(raw[0]), float(raw[1]), None)

    def _dwell_refresh(self):
        """Kursor stoi przy punkcie: ponowne wyliczenie podglądu (bez ruchu myszy), żeby przyciąganie się pokazało."""
        if self.mode != 'sketch' or self.view.snapper is None:
            return
        from PySide6.QtGui import QCursor
        pos = self.view.mapFromGlobal(QCursor.pos())
        if not self.view.rect().contains(pos):
            return
        self.view._hover_time = 0.0
        if self.view._sk_start is not None:      # przeciąganie kształtu (prostokąt, okrąg): odśwież podgląd jak przy ruchu
            point = self.view.plane_point(self.view.sketch_plane, pos.x(), pos.y())
            if point:
                from PySide6.QtCore import QPointF
                end = self.view._snap(point, pos=QPointF(pos))
                self.view._set_sketch_preview(self.view._sketch_outline(self.view.sketch_plane, self.view._sk_start, end))
            return
        from PySide6.QtCore import QPointF
        self.view._hover(QPointF(pos))

    def _wire(self, points):
        t = self.tool
        if t in ('line', 'construction'):
            return kernel.polyline(self.sketch_plane, points, False)
        if t == 'arc':
            return kernel.arc3(self.sketch_plane, points)
        if t == 'rect3':
            return kernel.rect3(self.sketch_plane, points)
        if t == 'point':
            return kernel.point_marker(self.sketch_plane, points[0])
        return kernel.sketch_shape(t, self.sketch_plane, points, self.sides)

    def _preview_points(self, pts):
        t, need = self.tool, NEED.get(self.tool, 2)
        if t == 'line':
            return kernel.polyline(self.sketch_plane, pts) if len(pts) >= 2 else None
        if t == 'measure':
            return kernel.polyline(self.sketch_plane, pts) if len(pts) == 2 else None
        if t in ('text', 'trim', 'offset', 'circleTangent2', 'point'):
            return None
        if len(pts) == need:
            return self._wire(pts)
        if t == 'circle3' and len(pts) == 2:
            return kernel.sketch_shape('circle2', self.sketch_plane, pts)
        if t in ('arc', 'rect3', 'slot') and len(pts) == 2:
            return kernel.polyline(self.sketch_plane, pts)
        return None

    def _show_sketch_preview(self, pts):
        try:
            shape = self._preview_points(pts)
            mesh = kernel.display_mesh(shape) if shape is not None else None
        except Exception:
            mesh = None
        self.view.set_preview_mesh(mesh, line_color=SKETCH_ORANGE, width=2, dashed=True)

    # ---------- tekst: kreator (powierzchnia -> obszar -> treść, uchwyty skalowania i obrotu) ----------
    def _text_begin(self):
        """Start narzędzia Tekst: zawsze najpierw wybór powierzchni (po jej wskazaniu kreator przechodzi do obszaru)."""
        keep = getattr(self, '_text_plane_keep', False)
        self._text_plane_keep = False
        self.txt = dict(stage='area' if keep else 'surface', drag=None, anchor=(0.0, 0.0), size=self.text_size.value(), angle=0.0)
        self._text_ui()

    def _text_end(self):
        stage = (self.txt or {}).get('stage')
        self.txt = None
        self.view.sketch_box = None
        if stage == 'surface' and self.mode == 'sketch':
            self.view.plane_pick = False
            self.view.show_planes(False)
            self.view.setCursor(Qt.ArrowCursor)
        self.text_form.setEnabled(False)
        self.view.update()

    def _text_sample_update(self):
        """Podgląd napisu w panelu: wybrana czcionka, pogrubienie, pochylenie i wersaliki."""
        text = self.text_edit.text() or 'Tekst'
        if self.text_caps.isChecked():
            text = text.upper()
        family = self.text_font.currentFont().family()
        font = QFont(family)
        font.setPixelSize(30)
        font.setBold(self.text_bold.isChecked())
        font.setItalic(self.text_italic.isChecked())
        from PySide6.QtGui import QFontMetrics
        width = QFontMetrics(font).horizontalAdvance(text)
        size = 30 if width <= 260 else max(12, int(30 * 260 / width))      # długi napis mieści się w ramce
        # styl wprost na etykiecie (styl panelu ustala czcionkę etykiet i nadpisałby setFont)
        self.text_sample.setStyleSheet(
            f"QLabel#textSample {{ background:#ffffff; border:1.4px solid #d3e0ec; border-radius:12px; color:#27415a; padding:4px 10px;"
            f" font-family:'{family}'; font-size:{size}px; font-weight:{900 if self.text_bold.isChecked() else 400};"
            f" font-style:{'italic' if self.text_italic.isChecked() else 'normal'}; }}")
        self.text_sample.setText(text)

    def _text_set_stage(self, stage):
        if self.txt is None:
            return
        self.txt['stage'] = stage
        self.txt['drag'] = None
        self.view.set_preview_mesh(None)
        self._text_ui()

    def _text_ui(self):
        t = self.txt
        if t is None:
            return
        stage = t['stage']
        self.view.sketch_box = None
        self._hover_key = None
        self.view.plane_pick = stage == 'surface'
        self.view.show_planes(stage == 'surface')
        self.view.setCursor(Qt.PointingHandCursor if stage == 'surface' else Qt.CrossCursor)
        label = self._plane_label()
        if stage == 'surface':
            self.txt_step1.set_state('active', 'Kliknij płaszczyznę lub ścianę')
            self.txt_step2.set_state('pending', '')
        elif stage == 'area':
            self.txt_step1.set_state('done', f'Płaszczyzna {label}')
            self.txt_step2.set_state('active', 'Przytrzymaj lewy przycisk i przeciągnij')
        else:
            self.txt_step1.set_state('done', f'Płaszczyzna {label}')
            self.txt_step2.set_state('done', 'Przeciągnij uchwyty, aby zmienić')
        self.text_form.setEnabled(stage == 'edit')
        self.text_status.setText({'surface': 'Wybierz, gdzie ma być napis.', 'area': 'Zaznacz prostokątny obszar napisu na powierzchni.',
                                  'edit': 'Wpisz treść. Niebieski uchwyt skaluje, czerwony punkt obraca, wnętrze ramki przesuwa. Enter zatwierdza.'}[stage])
        if stage == 'edit':
            self._text_refresh()
            self.text_edit.setFocus()
            self.text_edit.selectAll()
        self._fit_panel(self.text_panel, 88 + TOOLS_TOP - 18)
        self.view.update()

    def _text_params(self):
        text = self.text_edit.text().replace('\n', ' ')
        return dict(text=text.upper() if self.text_caps.isChecked() else text, font=self.text_font.currentFont().family(),
                    bold=self.text_bold.isChecked(), italic=self.text_italic.isChecked())

    def _text_shapes(self):
        t, q = self.txt, self._text_params()
        return kernel.text_shape(self.sketch_plane, q['text'], *t['anchor'], size=t['size'], font=q['font'], bold=q['bold'], italic=q['italic'], angle=t['angle'])

    def _text_extent(self):
        q = self._text_params()
        key = (self._plane_key(self.sketch_plane), q['text'], q['font'], q['bold'], q['italic'])
        if key not in self._text_ext:
            if len(self._text_ext) > 40:
                self._text_ext.clear()
            self._text_ext[key] = kernel.text_extent(self.sketch_plane, q['text'], q['font'], q['bold'], q['italic'])
        return self._text_ext[key]

    def _text_geometry(self):
        """Ramka napisu w układzie szkicu i uchwyty: narożniki BL, BR, TR, TL, skalowanie (BR), obrót (czerwony punkt przy TR), przesuwanie (środek)."""
        t = self.txt
        u0, v0, u1, v1 = self._text_extent()
        f = t['size'] / 10.0
        m = max(.4, t['size'] * .08)
        local = [(u0 * f - m, v0 * f - m), (u1 * f + m, v0 * f - m), (u1 * f + m, v1 * f + m), (u0 * f - m, v1 * f + m)]
        d = max(t['size'] * .32, 2.5) / math.sqrt(2)
        local_rot = (local[2][0] + d, local[2][1] + d)
        a = math.radians(t['angle'])
        ca, sa = math.cos(a), math.sin(a)
        place = lambda p: (t['anchor'][0] + p[0] * ca - p[1] * sa, t['anchor'][1] + p[0] * sa + p[1] * ca)
        corners = [place(p) for p in local]
        center = place(((local[0][0] + local[2][0]) / 2, (local[0][1] + local[2][1]) / 2))
        return dict(corners=corners, scale=corners[1], rotate=place(local_rot), move=center)

    def _text_box_world(self):
        g = self._text_geometry()
        w = lambda p: kernel.to_world(self.sketch_plane, *p)
        return dict(corners=[w(c) for c in g['corners']], scale=w(g['scale']), rotate=w(g['rotate']), move=w(g['move']))

    def _text_refresh(self):
        """Podgląd napisu na żywo + ramka z uchwytami."""
        t = self.txt
        if t is None or t.get('stage') != 'edit' or self.mode != 'sketch':
            return
        try:
            shapes = self._text_shapes()
            mesh = _merge_meshes([kernel.display_mesh(w) for w in shapes])
            self.view.set_preview_mesh(mesh, line_color=SKETCH_ORANGE, width=2.2)
            self.view.sketch_box = self._text_box_world()
            self.text_status.setText('Wpisz treść. Niebieski uchwyt skaluje, czerwony punkt obraca, wnętrze ramki przesuwa. Enter zatwierdza.')
        except Exception as exc:
            self.view.set_preview_mesh(None)
            self.view.sketch_box = None
            self.text_status.setText(str(exc) or 'Nie udało się utworzyć napisu.')
        self.view.update()

    def _text_spin_changed(self):
        t = self.txt
        if t is None or t.get('stage') != 'edit' or t.get('syncing'):
            return
        t['size'] = max(.1, self.text_size.value())
        t['angle'] = self.text_angle.value()
        self._text_refresh()

    def _text_sync_spins(self):
        t = self.txt
        t['syncing'] = True
        for spin, value in ((self.text_size, t['size']), (self.text_angle, t['angle'])):
            spin.blockSignals(True)
            spin.setValue(round(value, 2))
            spin.blockSignals(False)
        t['syncing'] = False

    def _text_hit(self, x, y):
        box = self._text_box_world()
        for which in ('rotate', 'scale'):
            xy = self.view.project_one(box[which])
            if xy is not None and math.hypot(xy[0] - x, xy[1] - y) <= 16:
                return which
        pts = [self.view.project_one(c) for c in box['corners']]
        if all(q is not None for q in pts):
            from PySide6.QtCore import QPointF
            from PySide6.QtGui import QPolygonF
            if QPolygonF([QPointF(*q) for q in pts]).containsPoint(QPointF(x, y), Qt.OddEvenFill):
                return 'move'
        return None

    def _text_hook(self, kind, x, y):
        """Mysz w kreatorze tekstu: przeciągnięcie obszaru, potem uchwyty ramki (skala / obrót / przesunięcie)."""
        t = self.txt
        if t is None or t['stage'] == 'surface':
            return False
        plane = self.sketch_plane
        if kind == 'press':
            uv = self.view.plane_point(plane, x, y)
            if uv is None:
                return True
            if t['stage'] == 'edit':
                which = self._text_hit(x, y)
                if which is not None:
                    g = self._text_geometry()
                    t['drag'] = dict(kind=which, uv0=uv, anchor0=t['anchor'], size0=t['size'], angle0=t['angle'], scale0=g['scale'], rot0=g['rotate'])
                    return True
            t['drag'] = dict(kind='area', uv0=uv, uv1=uv)
            return True
        drag = t.get('drag')
        if drag is None:
            return True
        uv = self.view.plane_point(plane, x, y)
        if kind == 'move':
            if uv is None:
                return True
            if drag['kind'] == 'area':
                drag['uv1'] = uv
                try:
                    self.view.set_preview_mesh(kernel.display_mesh(kernel.sketch_shape('rect', plane, [drag['uv0'], uv])), line_color=SKETCH_ORANGE, width=2, dashed=True)
                except Exception:
                    pass
                return True
            a0 = drag['anchor0']
            if drag['kind'] == 'move':
                t['anchor'] = (a0[0] + uv[0] - drag['uv0'][0], a0[1] + uv[1] - drag['uv0'][1])
            elif drag['kind'] == 'scale':
                r0 = math.hypot(drag['scale0'][0] - a0[0], drag['scale0'][1] - a0[1])
                r1 = math.hypot(uv[0] - a0[0], uv[1] - a0[1])
                if r0 > 1e-9:
                    t['size'] = min(5000.0, max(.1, drag['size0'] * r1 / r0))
            else:
                ang = math.degrees(math.atan2(uv[1] - a0[1], uv[0] - a0[0]) - math.atan2(drag['rot0'][1] - a0[1], drag['rot0'][0] - a0[0]))
                ang = (drag['angle0'] + ang + 180.0) % 360.0 - 180.0
                t['angle'] = round(ang, 1)
            self._text_sync_spins()
            self.view.transform_preview_uv(plane, a0, t['anchor'], t['size'] / drag['size0'], t['angle'] - drag['angle0'])   # płynnie: tylko macierz
            self.view.sketch_box = self._text_box_world()
            self.view.update()
            return True
        if kind == 'release':
            t['drag'] = None
            if drag['kind'] == 'area':
                self._text_area_done(drag['uv0'], drag.get('uv1', drag['uv0']))
            else:
                self._text_refresh()   # dokładna geometria po puszczeniu przycisku
            return True
        return True

    def _text_area_done(self, p0, p1):
        t = self.txt
        w, h = abs(p1[0] - p0[0]), abs(p1[1] - p0[1])
        self.view.set_preview_mesh(None)
        try:
            u0, v0, u1, v1 = self._text_extent()
            ew, eh = max(u1 - u0, 1e-6), max(v1 - v0, 1e-6)
            if w < .5 or h < .5:      # samo kliknięcie: napis o bieżącej wysokości, lewy dolny róg w klikniętym punkcie
                size = t['size']
                t['anchor'] = (p0[0] - u0 * size / 10.0, p0[1] - v0 * size / 10.0)
            else:
                size = min(5000.0, max(.1, min(w / ew, h / eh) * 10.0))
                cu, cv = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
                t['anchor'] = (cu - (u0 + u1) / 2 * size / 10.0, cv - (v0 + v1) / 2 * size / 10.0)
            t['size'], t['angle'] = size, 0.0
        except Exception as exc:
            self.toast(str(exc) or 'Wpisz treść napisu.')
            return
        self._text_sync_spins()
        self._text_set_stage('edit')

    def apply_text(self):
        t = self.txt
        if self.busy or self.mode != 'sketch' or self.tool != 'text' or t is None:
            return
        if t['stage'] != 'edit':
            self.toast('Najpierw wybierz powierzchnię i zaznacz obszar napisu.')
            return
        try:
            shapes = self._text_shapes()
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        self.view.set_preview_mesh(None)
        q, t = self._text_params(), self.txt
        self.create_sketch(shapes, 'Tekst', op=dict(type='text', params=dict(text=q['text'], anchor=[float(c) for c in t['anchor']], size=float(t['size']), font=q['font'],
                                                                      bold=bool(q['bold']), italic=bool(q['italic']), angle=float(t['angle']))))
        self._text_set_stage('area')   # kolejny napis na tej samej powierzchni

    def text_cancel(self):
        if self.txt is not None and self.txt['stage'] == 'edit':
            self._text_set_stage('area')
        else:
            self.choose_tool('rect')

    def sketch_moved(self, plane, u, v):
        if self.mode != 'sketch' or self.busy:
            return
        self.last_uv = (u, v)
        drawing = bool(self.points) or (self.tool == 'circleTangent2' and bool(self.tangent_lines))
        self.view.set_marker(kernel.to_world(self.sketch_plane, u, v), label=self.view.snap_label)
        if self.tool == 'trim':
            self.trim_preview()
            return
        if self.tool == 'offset':
            if self.off is None:
                self._off_hover()
            return
        if self.tool == 'circleTangent2':
            if len(self.tangent_lines) == 2:
                try:
                    shape = kernel.circle_tangent2(self.sketch_plane, *self.tangent_lines, (u, v))
                    self.view.set_preview_mesh(kernel.display_mesh(shape), line_color=SKETCH_ORANGE, width=2, dashed=True)
                except kernel.CadError:
                    self.view.set_preview_mesh(None)
            return
        if not self.points or self.dim_panel.isVisible():
            return          # wartości wpisane z klawiatury mają pierwszeństwo przed kursorem
        if self.tool == 'polygon' and len(self.points) == 1:
            end = self._polygon_end((u, v))
            if end is not None:
                u, v = end
        pts = [*self.points, (u, v)]
        self._show_sketch_preview(pts)
        self.show_dimension(pts)

    def _polygon_end(self, snapped=None):
        """Wielokąt: pierwszy wierzchołek jest zawsze w punkcie kursora - także przyciągniętym (kratka siatki, krawędź,
        wierzchołek szkicu lub bryły). Odległość od środka to wielkość, kierunek - obrót; nic nie przeskakuje,
        gdy przyciąganie się włącza / wyłącza. Zwraca punkt pierwszego wierzchołka (u, v)."""
        center = self.points[0]
        if snapped is None:
            return None
        du, dv = snapped[0] - center[0], snapped[1] - center[1]
        if math.hypot(du, dv) <= 1e-6:
            return None
        self._poly_end = (float(snapped[0]), float(snapped[1]))
        self._poly_angle = round(math.degrees(math.atan2(dv, du)) - 90, 2)
        return self._poly_end

    def show_dimension(self, pts):
        a, b = self.points[0], pts[-1]
        if self.tool == 'line' and len(pts) > 2:
            a = pts[-2]
        du, dv = abs(b[0] - a[0]), abs(b[1] - a[1])
        dist = math.hypot(b[0] - a[0], b[1] - a[1])
        if self.tool in ('rect', 'ellipse'):
            text = f'{fmt(du)} × {fmt(dv)} mm'
        elif self.tool == 'centerRect':
            text = f'{fmt(2 * du)} × {fmt(2 * dv)} mm'
        elif self.tool == 'polygon':
            text = f'R {fmt(dist)} mm · obrót {getattr(self, "_poly_angle", 0):g}° · {self.sides} kątów'
        elif self.tool == 'circle':
            text = f'R {fmt(dist)} mm'
        elif self.tool == 'circle2':
            text = f'Ø {fmt(dist)} mm'
        else:
            text = f'{fmt(dist)} mm'
        self.dim.setText(text)
        self.dim.adjustSize()
        pos = self.view.mapFromGlobal(QCursor.pos())
        self.dim.move(pos.x() + 14, pos.y() + 12)
        self.dim.show()
        self.dim.raise_()

    def _cursor_edge(self):
        pos = self.view.mapFromGlobal(QCursor.pos())
        return self.view.nearest_edge(pos.x(), pos.y(), kinds=('sketch',))

    @staticmethod
    def _same_plane(a, b):
        """Ta sama płaszczyzna (kierunek osi U może być inny - np. szkic na ścianie otwarty ponownie)."""
        if a is None or b is None:
            return False
        if isinstance(a, str) and isinstance(b, str):
            return a == b
        fa, fb = kernel.frame_of(a), kernel.frame_of(b)
        na, nb = np.asarray(fa.normal, float), np.asarray(fb.normal, float)
        if abs(abs(float(na @ nb)) - 1) > 1e-6:
            return False
        return abs(float((np.asarray(fb.origin, float) - np.asarray(fa.origin, float)) @ na)) < 1e-4

    def _edge_line(self):
        hit = self._cursor_edge()
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'sketch':
            raise kernel.CadError('Kliknij prostą linię narysowanego szkicu.')
        edge = body.shape.Edges()[hit[1]]
        if edge.geomType() != 'LINE':
            raise kernel.CadError('Wybierz prostą linię (nie łuk ani okrąg).')
        return kernel.uv_of(self.sketch_plane, edge.startPoint().toTuple()), kernel.uv_of(self.sketch_plane, edge.endPoint().toTuple())

    def sketch_clicked(self, plane, u, v):
        if self.mode != 'sketch' or self.busy:
            return
        t = self.tool
        try:
            if t == 'trim':
                self.trim_at_cursor()
                return
            if t == 'offset':
                self.pick_offset()
                return
            if t == 'circleTangent2':
                if len(self.tangent_lines) < 2:
                    self.tangent_lines.append(self._edge_line())
                    self.show_sketch_hint()
                    return
                shape = kernel.circle_tangent2(self.sketch_plane, *self.tangent_lines, (u, v))
                self.tangent_lines = []
                self.view.set_preview_mesh(None)
                self.create_sketch([shape])
                return
            if t == 'text':
                return
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        if t == 'line':
            if len(self.points) >= 3 and kernel_close(self.points[0], (u, v)):
                self.finish_line(closed=True)
                return
            if self.points and kernel_close(self.points[-1], (u, v)):
                self.finish_line()
                return
            self.points.append((u, v))
            self.show_sketch_hint()
            return
        if t == 'polygon' and len(self.points) == 1:
            end = self._polygon_end((u, v))
            if end is not None:
                u, v = end
        self.points.append((u, v))
        if len(self.points) < NEED[t]:
            self.show_sketch_hint()
            return
        points, self.points = list(self.points), []
        self._poly_end = None
        self.complete(points)

    def finish_line(self, closed=False):
        points, self.points = list(self.points), []
        self.dim.hide()
        self.dim_panel.hide()
        self.view.set_preview_mesh(None)
        if len(points) < 2:
            self.show_sketch_hint()
            return
        try:
            meta = dict(tool='line', points=[list(p) for p in points], sides=self.sides) if len(points) == 2 and not closed else None
            self.create_sketch([kernel.polyline(self.sketch_plane, points, closed)], None, meta)
        except kernel.CadError as exc:
            self.toast(str(exc))

    def complete(self, points):
        """Zebrane punkty tworzą gotowy element szkicu (lub pomiar)."""
        self.dim.hide()
        self.dim_panel.hide()
        self.view.set_preview_mesh(None)
        try:
            if self.tool == 'measure':
                (a, b) = points[:2]
                self.toast(f'Odległość: {fmt(math.hypot(b[0] - a[0], b[1] - a[1]))} mm   (ΔU {fmt(abs(b[0] - a[0]))}, ΔV {fmt(abs(b[1] - a[1]))})', 8000)
                return
            shape = self._wire(points)
        except kernel.CadError as exc:
            self.toast(str(exc))
            self.show_sketch_hint()
            return
        meta = dict(tool=self.tool, points=[list(p) for p in points], sides=self.sides) if self.tool in self.EDITABLE and self.tool not in ('line', 'text') else None
        self.create_sketch([shape], 'Konstrukcja' if self.tool == 'construction' else ('Punkt' if self.tool == 'point' else None), meta)

    def create_sketch(self, shapes, label=None, meta=None, select=False, op=None):
        plane = self.sketch_plane
        name = f'{label or "Szkic"} {self._plane_label()}'
        ids = (hist.text_ids(hist.new_text_group(), len(shapes)) if op.get('type') == 'text' else [uuid.uuid4().hex for _ in shapes]) if op else None
        if op:
            op = dict(op, plane=hist.plane_to_json(plane), name=name, out=ids)
        made = [replace(Body(name, sh, 'sketch', plane).prepared(), meta=meta) for sh in shapes] if select else None

        def after():
            if select and made:
                self.choose_tool(None)
                self.selected = [made[-1].id]
                self.refresh()
                self._update_grips()
                self.sk_hint.setText('Tekst: przesuń, skaluj lub obróć uchwytami · Tab – wysokość i kąt')

        if op and op.get('type') == 'text':          # napis od razu jako grupa na liście obiektów
            folder = hist.text_folder(op['params']['text'])
            if made:
                made = [replace(b, folder=folder) for b in made]
        else:
            folder = ''

        def commit_new(bodies):
            if folder:
                bodies = [replace(b, folder=folder) for b in bodies]
            self.document.pending_op = op
            if op and op.get('type') == 'text':
                self.document.pending_icon = 'text'
            self.add_prepared_many(bodies)

        self.run_operation('Tworzenie szkicu', (lambda: made) if select else
                           (lambda: [replace(Body(name, sh, 'sketch', plane, id=(ids[i] if ids else uuid.uuid4().hex)).prepared(), meta=meta) for i, sh in enumerate(shapes)]),
                           commit_new, after=after if select else None)
        self.show_sketch_hint()

    def add_prepared_many(self, bodies):
        self.document.commit((*self.document.bodies, *bodies))
        if bodies and bodies[-1].meta:
            self._last_sketch_id = bodies[-1].id
        if self.mode != 'sketch':
            self._tool_select([b.id for b in bodies], sketch=all(b.kind == 'sketch' for b in bodies))

    def _trim_target(self):
        """Szkic i kawałek jego krawędzi (między przecięciami z innymi szkicami) najbliższy kursorowi."""
        pos = self.view.mapFromGlobal(QCursor.pos())
        hit = self.view.nearest_edge(pos.x(), pos.y())
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'sketch':
            return None
        key = self._plane_key(body.plane)
        plane, bodies = self._drawn_sketches().get(key, (None, []))
        if body not in bodies:
            return None
        sig = (key, tuple((b.id, id(b.shape)) for b in bodies), body.id)
        if self._trim_cache is None or self._trim_cache[0] != sig:
            self._trim_cache = (sig, kernel.trim_pieces([b.shape.Edges() for b in bodies], bodies.index(body)))
        pieces = self._trim_cache[1]
        uv = self.view.plane_point(body.plane, pos.x(), pos.y())
        if not pieces or uv is None:
            return None
        import cadquery as cq
        vertex = cq.Vertex.makeVertex(*[float(c) for c in kernel.to_world(body.plane, *uv)])
        index = min(range(len(pieces)), key=lambda i: pieces[i].distance(vertex))
        return body, pieces, index

    def trim_preview(self):
        try:
            target = self._trim_target()
            mesh = kernel.display_mesh(target[1][target[2]], PREVIEW_TOL) if target else None
        except Exception:
            mesh = None
        self.view.set_preview_mesh(mesh, line_color=(.9, .18, .18, 1), width=5)

    def trim_at_cursor(self):
        target = self._trim_target()
        if target is None:
            raise kernel.CadError('Kliknij fragment szkicu.')
        body, pieces, index = target

        recipe = dict(type='trim', id=body.id, mid=[float(c) for c in pieces[index].positionAt(.5).toTuple()], out=[])
        existing = list(self.document.bodies)

        def build():
            return list(hist.run_trim(existing, recipe))

        def apply(bodies):
            old = {b.id for b in existing}
            recipe['out'] = [b.id for b in bodies if b.id not in old]
            self.document.pending_op = recipe
            self.document.commit(bodies)

        self.view.set_preview_mesh(None)
        self.run_operation('Nożyczki', build, apply)
    # ---------- ofset szkicu ----------
    def _off_body_at_cursor(self):
        """Szkic pod kursorem leżący w płaszczyźnie bieżącego szkicu i punkt kliknięcia na tej płaszczyźnie."""
        pos = self.view.mapFromGlobal(QCursor.pos())
        # tylko linie szkiców: szkic narysowany dokładnie po obrysie ściany ma linie w miejscu krawędzi bryły
        hit = self.view.nearest_edge(pos.x(), pos.y(), kinds=('sketch',))
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'sketch' or body.name.startswith('Punkt'):
            return None, None
        if not self._same_plane(body.plane, self.sketch_plane):
            return None, None
        uv = self.view.plane_point(body.plane, pos.x(), pos.y())
        point = kernel.to_world(body.plane, *uv) if uv is not None else body.shape.Center().toTuple()
        return body, point

    def _off_hover(self):
        try:
            body, _ = self._off_body_at_cursor()
            mesh = kernel.display_mesh(body.shape, PREVIEW_TOL) if body is not None else None
        except Exception:
            mesh = None
        self.view.set_preview_mesh(mesh, line_color=(.1, .45, .85, 1), width=5)

    def pick_offset(self):
        body, point = self._off_body_at_cursor()
        if body is None:
            raise kernel.CadError('Kliknij linię kształtu narysowanego w tym szkicu.')
        base, direction = kernel.offset_anchor(body.shape, body.plane, point)
        self.off = dict(id=body.id, base=base, dir=direction)
        self.off_step.set_state('done', body.name)
        self._off_update()
        self.hint('Przeciągnij strzałkę albo wpisz odległość; Enter zatwierdza, Esc wybiera inny kształt.')
        self.off_value.setFocus()
        self.off_value.selectAll()

    def _off_signed(self):
        return self.off_value.value() * (1.0 if self.off_side.currentData() == 'out' else -1.0)

    def _off_set_signed(self, value):
        """Wartość ze strzałki: znak wybiera stronę (na zewnątrz / do wewnątrz), wartość bezwzględna - odległość."""
        value = round(float(value), 1)
        if abs(value) < .1:
            value = .1 if value >= 0 else -.1
        for w in (self.off_side, self.off_value):
            w.blockSignals(True)
        try:
            self.off_side.setCurrentIndex(self.off_side._data.index('out' if value > 0 else 'in'))
            self.off_value.setValue(abs(value))
        finally:
            for w in (self.off_side, self.off_value):
                w.blockSignals(False)
        self._off_update(handle=False)

    def _off_result(self):
        body = self.document.get(self.off['id']) if self.off else None
        if body is None:
            raise kernel.CadError('Kliknij kształt szkicu.')
        return body, kernel.sketch_offset(body.shape, body.plane, self._off_signed())

    def _off_update(self, handle=True):
        if self.off is None:
            return
        import cadquery as cq
        try:
            _, wires = self._off_result()
            self.view.set_preview_mesh(kernel.display_mesh(cq.Compound.makeCompound(wires), PREVIEW_TOL), line_color=SKETCH_ORANGE, width=2.6, dashed=True)
            side = 'na zewnątrz' if self._off_signed() > 0 else 'do wewnątrz'
            self.off_status.setText(f'{self.off_value.value():g} mm {side} · Enter zatwierdza'.replace('.', ','))
        except kernel.CadError as exc:
            self.view.set_preview_mesh(None)
            self.off_status.setText(str(exc))
        if handle:
            self._off_place_handle()

    def _off_place_handle(self):
        if self.off is None or self.mode != 'sketch' or self.tool != 'offset':
            self.view.set_handles([])
            return
        base, direction = np.asarray(self.off['base'], float), np.asarray(self.off['dir'], float)
        self.view.set_handles([dict(id='off', start=base, tip=base + direction * self._off_signed(), dir=direction, color=(.94, .6, .13, 1), label='')])

    def _off_clear(self):
        if getattr(self, 'off', None) is not None:
            self.off = None
            self.view.set_handles([])
            self.view.set_preview_mesh(None)
        if hasattr(self, 'off_step'):
            self.off_step.set_state('active', '')
            self.off_status.setText('Kliknij kształt szkicu.')

    def cancel_offset(self):
        if self.off is not None:
            self._off_clear()
            self.show_sketch_hint()
        else:
            self.choose_tool(None)

    def apply_offset(self):
        if self.busy or self.off is None:
            return
        try:
            body, wires = self._off_result()
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        self._off_clear()
        self.create_sketch(wires, 'Ofset')

    # ---------- wymiary z klawiatury (panel jak #dimensionPanel, podgląd na żywo) ----------
    def open_dim_input(self, first=''):
        labels = DIM_LABELS.get(self.tool)
        if self.mode != 'sketch' or not self.points or not labels:
            return False
        self._dim_target = None
        current = self._current_dims()
        for i in range(len(self.dim_edits)):
            visible = i < len(labels)
            self.dim_labels[i].setVisible(visible)
            self.dim_edits[i].setVisible(visible)
            if visible:
                self.dim_labels[i].setText(labels[i])
                self.dim_edits[i].blockSignals(True)
                # Tab: pola od razu z bieżącymi wymiarami (zaznaczone - wpisanie liczby je zastępuje); cyfra: zaczyna wpisywanie
                self.dim_edits[i].setText(first if (first and i == 0) else (current[i] if i < len(current) else ''))
                self.dim_edits[i].blockSignals(False)
        pos = self.view.mapFromGlobal(QCursor.pos())
        self.dim_panel.adjustSize()
        self.dim_panel.move(max(0, min(pos.x() + 16, self.view.width() - self.dim_panel.width() - 10)),
                            max(0, min(pos.y() + 14, self.view.height() - self.dim_panel.height() - 10)))
        self.dim_panel.show()
        self.dim_panel.raise_()
        self.dim_edits[0].setFocus()
        if first:
            self.dim_edits[0].setCursorPosition(len(first))
        else:
            self.dim_edits[0].selectAll()
        self.dim.hide()
        self.update_dim_preview()
        return True

    def _current_dims(self):
        """Wymiary rysowanego kształtu w tej chwili (z położenia kursora) - tekst do pól okna wymiarów."""
        if not self.points or self.last_uv is None:
            return []
        a = self.points[-1] if self.tool == 'line' else self.points[0]
        b = self._poly_end if (self.tool == 'polygon' and getattr(self, '_poly_end', None) is not None) else self.last_uv
        du, dv = b[0] - a[0], b[1] - a[1]
        dist = math.hypot(du, dv)
        angle = math.degrees(math.atan2(dv, du))
        t = self.tool
        if t == 'rect':
            values = [abs(du), abs(dv)]
        elif t in ('centerRect', 'ellipse'):
            values = [2 * abs(du), 2 * abs(dv)]
        elif t in ('circle', 'circle2'):
            values = [dist]
        elif t == 'polygon':
            values = [dist, angle - 90]           # obrót: 0° = wierzchołek u góry
        else:
            values = [dist, angle]
        return [fmt(v) for v in values]

    def _typed_values(self):
        values = []
        for edit in self.dim_edits:
            if edit.isVisible():
                try:
                    values.append(float(edit.text().replace(',', '.')))
                except ValueError:
                    values.append(None)
        return values

    def typed_end(self):
        v = self._typed_values()
        if not v or v[0] is None:
            return None
        self._apply_typed_sides(v)
        p0 = self.points[-1] if self.tool == 'line' else self.points[0]
        return self._dim_end(self.tool, p0, self.last_uv, v)

    def _apply_typed_sides(self, v):
        pass        # liczba kątów wielokąta ustawia się na pasku kształtów (strzałka przy wielokącie)

    @staticmethod
    def _dim_end(t, p0, ref, v, direction=None):
        """Punkt końcowy figury z wpisanych wymiarów; ref wyznacza stronę (znaki), direction - kierunek promienia."""
        u0, v0 = p0
        sx = 1 if ref[0] >= u0 else -1
        sy = 1 if ref[1] >= v0 else -1
        if t in ('rect', 'ellipse', 'centerRect'):
            w = v[0]
            h = v[1] if len(v) > 1 and v[1] is not None else v[0]
            k = .5 if t in ('centerRect', 'ellipse') else 1
            return (u0 + sx * w * k, v0 + sy * h * k)
        if t == 'polygon':                 # promień i obrót (kąt pierwszego wierzchołka)
            ang = math.radians(v[1] + 90) if len(v) > 1 and v[1] is not None else math.atan2(ref[1] - v0, ref[0] - u0)
            return (u0 + v[0] * math.cos(ang), v0 + v[0] * math.sin(ang))
        if t in ('circle', 'circle2'):
            d = direction or (1.0, 0.0)
            return (u0 + v[0] * d[0], v0 + v[0] * d[1])
        ang = math.radians(v[1]) if len(v) > 1 and v[1] is not None else 0.0
        return (u0 + v[0] * math.cos(ang), v0 + v[0] * math.sin(ang))

    # ---------- edycja wymiarów istniejącego szkicu (Tab po zaznaczeniu) ----------
    EDITABLE = sm.EDITABLE

    def _sketch_edit_target(self):
        chosen = [b for b in (self.document.get(i) for i in self.selected) if b is not None and b.kind == 'sketch' and b.meta]
        if len(chosen) == 1:
            return chosen[0]
        last = self.document.get(getattr(self, '_last_sketch_id', None)) if getattr(self, '_last_sketch_id', None) else None
        return last if last is not None and last.meta else None

    @staticmethod
    def _meta_shape(plane, meta):
        t = meta['tool']
        pts = [tuple(p) for p in meta['points']]
        if t == 'line':
            return kernel.polyline(plane, pts, False)
        if t == 'arc':
            return kernel.arc3(plane, pts)
        if t == 'rect3':
            return kernel.rect3(plane, pts)
        return kernel.sketch_shape(t, plane, pts, meta.get('sides', 5))

    def open_dim_edit(self):
        body = self._sketch_edit_target()
        if body is None or body.meta.get('tool') not in self.EDITABLE:
            self.toast('Zaznacz szkic narysowany z wymiarami (prostokąt, okrąg, wielokąt, elipsa, łuk, linia, tekst…).')
            return False
        self.selected = [body.id]
        self.refresh()
        self._update_grips()
        meta = body.meta
        tool = meta['tool']
        labels = sm.LABELS[tool]
        values = sm.values(meta)
        for i in range(len(self.dim_edits)):
            visible = i < len(labels)
            self.dim_labels[i].setVisible(visible)
            self.dim_edits[i].setVisible(visible)
            if visible:
                self.dim_labels[i].setText(labels[i])
                self.dim_edits[i].blockSignals(True)
                self.dim_edits[i].setText(values[i])
                self.dim_edits[i].blockSignals(False)
        self.dim_panel.adjustSize()
        self.dim_panel.move(max(0, (self.view.width() - self.dim_panel.width()) // 2), 90)
        self.dim_panel.show()
        self._dim_target = dict(body=body, meta=meta)
        self.dim_panel.raise_()
        self.dim_edits[0].setFocus()
        self.dim_edits[0].selectAll()
        self.dim.hide()
        self._dim_edit_shape()
        return True

    def _dim_edit_shape(self):
        """(kształt, nowe meta) z wpisanych wartości albo None."""
        t = self._dim_target
        v = self._typed_values()
        if t is None or not v or v[0] is None:
            return None
        try:
            meta = sm.apply_values(t['meta'], v)
            return self._meta_shape(t['body'].plane, meta), meta
        except Exception:
            return None

    def apply_dim_edit(self):
        result = self._dim_edit_shape()
        target = self._dim_target
        self.dim_panel.hide()
        self.view.setFocus()
        self.view.set_preview_mesh(None)
        if result is None or target is None:
            return
        self._commit_sketch_edit(target['body'], result[0], result[1])

    def _commit_sketch_edit(self, old, shape, meta):
        def build():
            return replace(old, shape=shape, mesh=kernel.display_mesh(shape), meta=meta)

        def apply(body):
            self.override = {}
            self.document.pending_op = dict(type='sketchmeta', id=body.id, meta=body.meta)
            self.document.commit([body if b.id == body.id else b for b in self.document.bodies])
            self._last_sketch_id = body.id
            self.selected = [body.id]
            self._update_grips()

        self.run_operation('Zmiana wymiarów szkicu', build, apply)

    # ---------- zaznaczanie i skalowanie kształtów myszą (szkic bez wybranego narzędzia) ----------
    def _update_grips(self, body=None, meta=None, mesh=None):
        grips = []
        if self.mode == 'sketch' and self.tool is None and len(self.selected) == 1:
            body = body or self.document.get(self.selected[0])
            if body is not None and body.meta and body.meta.get('tool') in self.EDITABLE:
                meta = meta or body.meta
                grips = [kernel.to_world(body.plane, *g) for g in sm.grip_points(meta)]
        self.view.sketch_grips = grips
        self.view.update()

    def _drag_label(self, meta, x, y):
        text = ' × '.join(sm.values(meta)[:2]) + ' mm'
        self.dim.setText(text)
        self.dim.adjustSize()
        self.dim.move(int(x) + 14, int(y) + 12)
        self.dim.show()

    def _sketch_hook(self, kind, x, y):
        if self.mode == 'sketch' and self.tool == 'text' and not self.busy:
            return self._text_hook(kind, x, y)
        if self.mode != 'sketch' or self.tool is not None or self.busy:
            return False
        if kind == 'press':
            self._sk_drag = None
            hit = self.view.nearest_edge(x, y, kinds=('sketch',))
            body = self.document.get(hit[0]) if hit else None
            if body is None:
                return False
            self.selected = [body.id]
            self.refresh()
            self._update_grips()
            if not body.meta or body.meta.get('tool') not in self.EDITABLE:
                self.sk_hint.setText('Zaznaczono szkic (brak wymiarów do edycji)')
                return True
            self.sk_hint.setText('Zaznaczono · Tab – wymiary · przeciągnij uchwyt lub krawędź')
            uv = self.view.plane_point(body.plane, x, y)
            if uv is None:
                return True
            pts = [tuple(p) for p in body.meta['points']]
            ppm = max(self.view._cam_ppm(), 1e-6)
            self._sk_drag = dict(kind='shape', body=body, meta=body.meta, new=None,
                                 grab=sm.grab_info(body.meta['tool'], pts, uv, 14.0 / ppm, body.meta))
            return True
        drag = getattr(self, '_sk_drag', None)
        if drag is None:
            return True
        body = drag['body']
        if kind == 'move':
            uv = self.view.plane_point(body.plane, x, y)
            if uv is None:
                return True
            meta2 = sm.grab_apply(drag['meta'], drag['grab'], uv)
            if meta2 is None:
                return True
            try:
                shape = self._meta_shape(body.plane, meta2)
                mesh = kernel.display_mesh(shape)
            except Exception:
                return True
            drag['new'] = (shape, meta2)
            self.override = {body.id: replace(body, shape=shape, mesh=mesh, meta=meta2)}
            self.refresh()
            self._update_grips(body, meta2, mesh)
            self._drag_label(meta2, x, y)
            return True
        if kind == 'release':
            self._sk_drag = None
            self.dim.hide()
            if drag['new'] is not None:
                self._commit_sketch_edit(body, drag['new'][0], drag['new'][1])
            else:
                self.override = {}
            return True
        return True

    def update_dim_preview(self):
        if self._dim_target is not None:
            result = self._dim_edit_shape()
            if self.dim_panel.isVisible() and result is not None:
                self.view.set_preview_mesh(kernel.display_mesh(result[0]), line_color=SKETCH_ORANGE, width=2.4)
            return
        if not self.dim_panel.isVisible() or not self.points:
            return
        end = self.typed_end()
        if end is None:
            return
        self._show_sketch_preview([*self.points, end])
        self.view.set_marker(kernel.to_world(self.sketch_plane, *end), label='Wymiar')

    def apply_typed(self):
        if self._dim_target is not None:
            self.apply_dim_edit()
            return
        end = self.typed_end()
        self.dim_panel.hide()
        self.view.setFocus()
        if end is None:
            return
        if self.tool == 'line':
            self.points.append(end)
            self.show_sketch_hint()
            self._show_sketch_preview(list(self.points))
            return
        points, self.points = [*self.points, end], []
        self.complete(points)

    # =====================================================================
    # klikanie i najeżdżanie w widoku
    # =====================================================================
    def view_hover(self, x, y):
        if self.section_picking and not self.busy:
            self.section_hover(x,y);return
        if self.busy:
            return
        if self._lib_action is not None:
            self._library_hover(x, y)
            return
        try:
            if self.mode == 'plane' or (self.mode == 'sketch' and self.tool == 'text' and self.txt and self.txt['stage'] == 'surface'):
                frame, face = self.pick_surface(x, y)
                key = ('f', face.hashCode()) if face is not None else ('p', frame if isinstance(frame, str) else None)
                if key != self._hover_key:
                    self._hover_key = key
                    self.view.set_preview_mesh(kernel.display_mesh(face) if face is not None else None,
                                               color=(1, .55, .1, .35), line_color=SKETCH_ORANGE, width=2)
            elif self.mode == 'sketch' and self.tool is None:
                hit = self.view.nearest_edge(x, y, kinds=('sketch',))
                self.view._set_hover_edge(hit)
                self.view.setCursor(Qt.SizeAllCursor if hit else Qt.ArrowCursor)
            elif self.mode == 'mirror' and self.mirror_id and self.mirror_frame is None:
                self._hover_face_only(x, y)
            elif self.mode in ('mate', 'align') and not ('moving' in self.mt_pick and 'target' in self.mt_pick):
                self._hover_face_only(x, y)
            elif self.mode == 'pattern' and self.pat_id is None:
                self._pattern_hover(x, y)
            elif self.mode == 'pattern' and self.pat_id and self.pat_picking:
                target = self._pattern_target(x, y)
                self.view.hover_vertex = target
                self.view.overlay.update()
            elif self.mode == 'pattern' and self.pat_id and self.pat_kind.currentData() == 'path':
                self.view._set_hover_edge(self.view.nearest_edge(x, y))
            elif self.mode == 'mod':
                vertex = self.view.nearest_vertex(x, y)
                self.view.hover_vertex = vertex[1] if vertex else None
                self.view._set_hover_edge(None if vertex else self.view.nearest_edge(x, y, True))
                self.view.overlay.update()
            elif self.mode is None and self._planes_visible:
                name = self.view.plane_at(x, y)
                self.view._highlight_plane(name)
                self.view.setCursor(Qt.PointingHandCursor if name else Qt.ArrowCursor)
            elif self.mode == 'extrude' and not self.ex_profiles:
                self._hover_extrude(x, y)
            elif self.mode == 'extrude' and self.ex_extent.currentData() == 'upto':
                self._hover_extent_target(x, y)
            elif self.mode in MEASURE_MODES:
                self._measure_hover(x,y)
            elif self.mode in ('sheetpick', 'plyfoldpick', 'scale') or self.mode in DRAWING_MODES or (self.mode == 'rules' and self.rl_pick):
                self._hover_shell_solid(x, y)
            elif self.mode == 'sweep':
                if self.sw_profiles and self.sw_path is None:
                    self.view._set_hover_edge(self.view.nearest_edge(x, y))
                elif not self._result_preview:       # podgląd gotowej bryły nie może być zastępowany podświetleniem profilu pod kursorem
                    self._hover_extrude(x, y)
            elif self.mode == 'loft':
                if self.lf_kind.currentData() == 'point' and self.lf_profiles and self.lf_point is None:
                    vertex = self.view.nearest_vertex(x, y, solids_only=False)
                    self.view.hover_vertex = vertex[1] if vertex else None
                    self.view.overlay.update()
                elif not self._result_preview:
                    self._hover_extrude(x, y)
            elif self.mode == 'shell':
                self._hover_face_only(x, y) if self.sh_id else self._hover_shell_solid(x, y)
            elif self.mode == 'thread':
                self._th_hover(x, y)
            elif self.mode in PLY_MODES:
                self.ply_hover(x, y)
            elif self.mode == 'split':
                self._split_hover(x, y)
            elif self.mode == 'sheet':
                self._hover_face_only(x, y)
            elif self.mode in ('flange', 'hem', 'tabwall'):
                self.view._set_hover_edge(self.view.nearest_edge(x, y, True))
            elif self.mode == 'revolve' and (not self.rev_profiles or (self.rev_axis.currentData() == 'line' and self.rev_line is None)):
                if self.rev_profiles:
                    self.view._set_hover_edge(self.view.nearest_edge(x, y))
                else:
                    self._hover_extrude(x, y)
        except Exception:
            self._hover_key = None

    def _hover_face_only(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        face = None
        if body is not None and body.kind == 'solid':
            try:
                face, _ = self.view.face_at(body,hit, curved=True)
            except kernel.CadError:
                face = None
        key = ('mf', face.hashCode()) if face is not None else None
        if key != self._hover_key:
            self._hover_key = key
            self.view.set_preview_mesh(kernel.display_mesh(face) if face is not None else None, color=(1, .55, .1, .35), line_color=SKETCH_ORANGE, width=2)

    def _hover_extrude(self, x, y):
        blue = dict(color=(.35, .65, .94, .45), line_color=(.1, .3, .6, 1), width=2)
        try:
            src = self._profile_at(x, y)
        except kernel.CadError:
            src = None
        if src is not None and src.get('kind') == 'cyl' and self.mode != 'extrude':
            src = None
        if src is None:
            if self._hover_key is not None:
                self._hover_key = None
                self.view.set_preview_mesh(None)
            return
        face = src.get('face') or profile_face(src['wire'])
        key = src['cluster'] if src.get('kind') == 'cyl' else (src['kind'], src.get('id'), tuple(round(c, 3) for c in src['center']))
        if key != self._hover_key:
            self._hover_key = key
            self.view.set_preview_mesh(kernel.display_mesh(face) if face is not None else None, **blue)
    def view_clicked(self, x, y, shift, ctrl):
        if self.busy:
            return
        if self.section_picking:
            self.section_pick(x,y);return
        if self._repick is not None:
            self._repick_click(x, y)
            return
        if self._lib_action is not None:
            self._library_click(x, y)
            return
        if self.mode == 'sketch' and self.tool == 'text' and self.txt is not None:
            if self.txt['stage'] == 'surface':
                plane, _ = self.pick_surface(x, y, True)
                if plane is None:
                    self.toast('Kliknij płaszczyznę lub płaską ścianę bryły.')
                    return
                self._text_plane_keep = True
                self.enter_sketch(plane)
            return
        if self.mode == 'sketch':
            if self.tool is None and self.selected:
                self.selected = []
                self.refresh()
                self._update_grips()
                self.sk_hint.setText('Wybierz kształt do rysowania')
            return
        if self.mode == 'rules':
            if self.rl_pick:
                self.pick_rules_sheet(x, y)
            return
        if self.mode == 'sheetpick':
            self.pick_sheet_command(x, y)
            return
        if self.mode == 'plyfoldpick':
            self.pick_ply_fold(x, y)
            return
        if self.mode == 'plane':
            plane, _ = self.pick_surface(x, y, True)
            if plane is None:
                self.toast('Kliknij płaszczyznę lub płaską ścianę bryły.')
                return
            self.enter_sketch(plane)
        elif self.mode == 'extrude':
            if self.ex_profiles and not shift and self.ex_extent.currentData() == 'upto':
                self.pick_extent_target(x, y)
            else:
                self.pick_profile(x, y, shift)
        elif self.mode == 'revolve':
            self.pick_revolve(x, y, shift)
        elif self.mode == 'sweep':
            self.pick_sweep(x, y, shift)
        elif self.mode in MEASURE_MODES:
            self.pick_measure(x, y)
        elif self.mode == 'loft':
            self.pick_loft(x, y)
        elif self.mode == 'thread':
            self.pick_thread(x, y, shift)
        elif self.mode in PLY_MODES:
            self.ply_clicked(x, y, shift)
        elif self.mode == 'shell':
            self.pick_shell(x, y)
        elif self.mode == 'sheet':
            self.pick_sheet(x, y)
        elif self.mode in ('flange', 'hem'):
            self.pick_flange(x, y)
        elif self.mode == 'tabwall':
            self.pick_tabwall(x, y)
        elif self.mode == 'scale':
            self.pick_scale(x, y, shift)
        elif self.mode in DRAWING_MODES:
            self.pick_drawing(x, y)
        elif self.mode == 'bool':
            self.pick_bool(x, y)
        elif self.mode == 'mod':
            self.pick_edge(x, y, shift, ctrl)
        elif self.mode == 'mirror':
            self.pick_mirror(x, y)
        elif self.mode == 'split':
            self.pick_split(x, y)
        elif self.mode in ('mate', 'align'):
            self.pick_mate(x, y)
        elif self.mode == 'pattern':
            self.pick_pattern(x, y)
        elif self.mode in ('move', 'rotate'):
            self.pick_transform_target(x, y)
        elif self.mode is None:
            bid = self.pick_object(x, y)
            if bid is None and self._planes_visible and not (shift or ctrl):
                name = self.view.plane_at(x, y)
                if name:
                    self.enter_sketch(name)
                    return
            members = self._group_ids(bid)
            if bid is None:
                if not (shift or ctrl):
                    self.selected = []
            elif shift or ctrl:
                self.selected = [i for i in self.selected if i not in members] if bid in self.selected else [*self.selected, *[i for i in members if i not in self.selected]]
            else:
                self.selected = members          # obiekt z grupy zaznacza całą grupę
            self.refresh()

    def _group_ids(self, bid):
        """Obiekt razem z pozostałymi z jego grupy (np. szyk „jako jeden element”); bez grupy - sam obiekt."""
        body = self.document.get(bid) if bid else None
        if body is None or not body.group:
            return [bid] if bid else []
        return [b.id for b in self.document.bodies if b.group == body.group]

    def pick_object(self, x, y):
        """Obiekt pod kursorem. Linia szkicu blisko kursora ma pierwszeństwo przed bryłą, na której leży (szkic narysowany
        na ścianie łatwo wskazać, np. do cięcia bryły szkicem), a zamknięty szkic na ścianie wygrywa z samą ścianą."""
        hit = self.view.nearest_edge(x, y, kinds=('sketch',))
        if hit is not None:
            return hit[0]
        bid = self.view.pick_body(x, y)
        if bid is None:
            hit = self.view.nearest_edge(x, y)
            bid = hit[0] if hit else None
        return bid

    # =====================================================================
    # wyciąganie: profil szkicu albo ściana bryły, strzałka, podgląd na żywo
    # =====================================================================
    @staticmethod
    def _plane_key(plane):
        return plane if isinstance(plane, str) else (plane.origin, plane.xdir, plane.normal)

    def _drawn_sketches(self):
        """Szkice (bez konstrukcji i punktów) pogrupowane według płaszczyzn: klucz -> (płaszczyzna, [bryły])."""
        cached=getattr(self,'_drawn_cache',None)
        if cached is not None and cached[0] is self.document.bodies:return cached[1]
        groups = {}
        for b in self.document.bodies:
            if b.kind == 'sketch' and b.visible and not b.name.startswith(('Konstrukcja', 'Punkt')):
                cache = self.__dict__.setdefault('_frame_cache', LRU(max_entries=8192))
                hit = cache.get(id(b.shape))
                if hit is None or hit[0] is not b.shape or hit[2] != b.plane:
                    hit = cache[id(b.shape)] = (b.shape, kernel.actual_frame(b.shape, b.plane), b.plane)
                plane = hit[1]   # obrócony / przesunięty szkic ma własną płaszczyznę
                groups.setdefault(self._plane_key(plane), (plane, []))[1].append(b)
        self._drawn_cache=(self.document.bodies,groups)
        return groups

    def _regions_for(self, key, plane, bodies):
        solids = tuple((b.id, id(b.shape)) for b in self.document.bodies if b.kind == 'solid' and b.visible)
        sig = (tuple((b.id, id(b.shape)) for b in bodies), solids)
        cached = self._region_cache.get(key)
        if cached and cached[0] == sig:
            return cached[1]
        try:
            faces = kernel.regions(plane, [e for b in bodies for e in b.shape.Edges()], [b.shape for b in bodies if b.shape.IsClosed()])
        except Exception:
            faces = []
        if not faces:
            faces = [f for f in (profile_face(b.shape) for b in bodies if b.shape.IsClosed()) if f is not None]
        # szkic na ścianie bryły, wychodzący poza nią: część na ścianie i część poza nią to osobne obszary
        faces = hist.split_on_solids(plane, faces, self.document.bodies)
        self._region_cache[key] = (sig, faces)
        return faces

    def _region_at(self, x, y):
        """Obszar szkicu pod kursorem (nakładające się kształty tną się nawzajem): (odległość, płaszczyzna, ściana).
        Gdy kilka szkiców leży w tej samej płaszczyźnie (np. profil, z którego wyciągnięto bryłę, i nowy szkic na jej ścianie), wygrywa najmniejszy obszar."""
        found = []
        for key, (plane, bodies) in self._drawn_sketches().items():
            hit = self.view._plane_hit(plane, x, y)
            if hit is None:
                continue
            if not self.view.section_contains(hit[1]):continue
            faces=self._regions_for(key,plane,bodies)
            store=self.__dict__.setdefault('_region_bounds',LRU(max_entries=128))
            indexed=store.get((key,id(faces)))
            if indexed is None:
                boxes=[kernel.bounds(f) for f in faces]
                tree=BoundsTree([[b.xmin,b.ymin,b.zmin] for b in boxes],[[b.xmax,b.ymax,b.zmax] for b in boxes])
                indexed=(faces,tree);store[(key,id(faces))]=indexed
            for i in indexed[1].point(hit[1],1e-5):
                face=faces[i]
                if kernel.face_contains(face, hit[1]):
                    try:
                        area = float(face.Area())
                    except Exception:
                        area = float('inf')
                    found.append((hit[0], area, plane, face))
        if not found:
            return None
        nearest = min(f[0] for f in found)
        tol = max(5e-3, 1e-4 * nearest)
        t, _, plane, face = min((f for f in found if f[0] <= nearest + tol), key=lambda f: f[1])
        return (t, plane, face)

    def _face_with_holes(self, face, normal, point):
        """Wskazana ściana bryły z otworami po szkicach narysowanych na niej (okrąg, kwadrat, napis...): (obszar pod kursorem, pozostałe obszary ściany
        - np. wyspy wewnątrz liter o, a, d, p - oraz id szkiców-otworów). Wynik jest pamiętany, bo wskazywanie wywołuje to przy każdym ruchu myszy."""
        sketches = hist.coplanar_sketches(face, normal, self.document.bodies)
        if not sketches:
            return face, [], []
        key = (tuple(round(float(c), 4) for c in face.Center().toTuple()), tuple(round(float(c), 4) for c in normal), tuple((b.id, id(b.shape)) for b in sketches))
        cache = self.__dict__.setdefault('_face_hole_cache', {})
        if key not in cache:
            if len(cache) > 40:
                cache.clear()
            cache[key] = hist.face_with_holes(face, normal, self.document.bodies)
        regions, holes = cache[key]
        if not holes:
            return face, [], []
        main = next((r for r in regions if kernel.face_contains(r, point)), None)
        if main is None:
            main = max(regions, key=lambda r: r.Area())
        return main, [r for r in regions if r is not main], [b.id for b in holes]

    def _profile_at(self, x, y):
        region = self._region_at(x, y)
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        solid = None
        picked = None
        if body is not None and body.kind == 'solid':
            try:
                picked = self.view.face_at(body,hit, curved=True)
            except kernel.CadError:
                picked = None
        if picked is not None and picked[0].geomType() == 'CYLINDER':
            # ścianka otworu albo zewnętrzna powierzchnia walca: wyciąganie zmienia promień (+ dodaje materiał, - wycina)
            try:
                info = kernel.cylinder_info(picked[0], body.shape)
                p = tuple(float(c) for c in hit[2])
                n = kernel.cylinder_normal(info, p)
                ray = self.view._ray(x, y)
                t = float(np.linalg.norm(np.asarray(hit[2], float) - ray[0])) if ray else 0.0
                solid = (t, dict(kind='cyl', id=body.id, face=picked[0], cyl=info, wire=None, plane=None, normal=tuple(float(c) for c in n),
                                 center=p, hit=p, cluster=(body.id, 'cyl', round(info['radius'], 6), tuple(np.round(info['origin'], 4)))))
            except kernel.CadError:
                solid = None
            picked = None
        if picked is not None:
            face, normal = picked
            ray = self.view._ray(x, y)
            t = float(np.linalg.norm(np.asarray(hit[2], float) - ray[0])) if ray else 0.0
            sub, others, hole_ids = self._face_with_holes(face, normal, hit[2])
            cluster = (body.id, tuple(round(float(c), 4) for c in face.Center().toTuple()))
            make = lambda f, sibling: dict(kind='face', id=body.id, face=f, whole=face, holes=True, hole_ids=hole_ids, wire=f.outerWire(), plane=None, normal=tuple(float(c) for c in normal),
                                           center=f.Center().toTuple(), hit=tuple(float(c) for c in hit[2]), cluster=cluster, sibling=sibling)
            solid = (t, dict(make(sub, False), siblings=[make(f, True) for f in others]))      # wyspy ściany (wnętrza liter o, a, d...) wyciągają się razem z nią
        if region is not None and (solid is None or region[0] <= solid[0] + max(5e-3, 1e-4 * solid[0])):
            frame = kernel.frame_of(region[1])
            face = region[2]
            return self._with_group(self._with_letters(dict(kind='region', id=None, face=face, wire=face.outerWire(), plane=region[1], normal=tuple(frame.normal), center=face.Center().toTuple()), x, y), x, y)
        if solid is not None:
            return solid[1]
        bid = self.view.pick_profile(x, y)
        if bid is not None:
            body = self.document.get(bid)
            frame = kernel.frame_of(body.plane)
            normal = kernel.profile_normal(body.shape, frame.normal)   # szkic mógł zostać obrócony: wyciągamy wzdłuż jego rzeczywistej normalnej
            tilted = abs(float(np.dot(normal, frame.normal))) < 1 - 1e-6
            return self._with_group(dict(kind='sketch', id=bid, face=None, wire=body.shape, plane=None if tilted else body.plane, normal=normal, center=body.shape.Center().toTuple()), x, y)
        return None

    def _sketch_profile(self, body):
        frame = kernel.frame_of(body.plane)
        normal = kernel.profile_normal(body.shape, frame.normal)
        tilted = abs(float(np.dot(normal, frame.normal))) < 1 - 1e-6
        return dict(kind='sketch', id=body.id, face=None, wire=body.shape, plane=None if tilted else body.plane, normal=normal, center=body.shape.Center().toTuple())

    def _with_group(self, src, x, y):
        """Szkic z grupy (szyk „jako jeden element”): kliknięcie jednego wybiera do wyciągnięcia / wycięcia wszystkie szkice grupy
        (Shift + klik dodaje albo odejmuje całą grupę)."""
        try:
            if src.get('letters'):
                return src
            if src['kind'] == 'sketch':
                body = self.document.get(src['id'])
            else:
                plane = src['plane']
                found = self._drawn_sketches().get(self._plane_key(plane))
                hit = self.view._plane_hit(plane, x, y)
                if not found or hit is None:
                    return src
                body = next((b for b in found[1] if b.group and any(kernel.face_contains(m, hit[1]) for m in hist.material_faces([b]))), None)
            if body is None or not body.group:
                return src
            members = [b for b in self.document.bodies if b.group == body.group and b.kind == 'sketch' and b.id != body.id]
            if not members:
                return src
            cluster = ('group', body.group)
            siblings = []
            groups = self._drawn_sketches()
            wanted = {m.id: m for m in members}
            where = {}
            for key, (_, bodies) in groups.items():
                for b in bodies:
                    if b.id in wanted:
                        where.setdefault(key, []).append(wanted[b.id])
            covered = set()
            for key, mine in where.items():
                # obszary płaszczyzny liczone raz; każdy obszar przypisany do szkicu, w którego prostokącie leży jego punkt
                # wewnętrzny (dokładne sprawdzenie tylko dla tych kilku) - zamiast porównywać każdy szkic z każdym obszarem
                plane, bodies = groups[key]
                boxes = []
                for m in mine:
                    bb = kernel.bounds(m.shape)
                    boxes.append((np.array([bb.xmin, bb.ymin, bb.zmin]) - 1e-6, np.array([bb.xmax, bb.ymax, bb.zmax]) + 1e-6, m))
                tree=BoundsTree([lo for lo,hi,m in boxes],[hi for lo,hi,m in boxes])
                material = {}
                for f in self._regions_for(key, plane, bodies):
                    point = np.asarray(hist._inner_point(f), float)
                    for candidate in tree.point(point):
                        low,high,m=boxes[candidate]
                        if (point >= low).all() and (point <= high).all():
                            faces=material.get(m.id)
                            if faces is None:faces=material[m.id]=hist.material_faces([m])
                            if any(kernel.face_contains(face, point) for face in faces):
                                siblings.append(dict(kind='region', id=None, face=f, wire=f.outerWire(), plane=plane, normal=src['normal'],
                                                     center=f.Center().toTuple(), cluster=cluster))
                                covered.add(m.id)
                                break
            for member in members:
                if member.id not in covered and (member.shape.IsClosed() if hasattr(member.shape, 'IsClosed') else False):
                    siblings.append(dict(self._sketch_profile(member), cluster=cluster))
            return dict(src, cluster=cluster, siblings=[*src.get('siblings', ()), *siblings])
        except Exception:
            return src
    def _with_letters(self, src, x, y):
        """Obszar litery napisu: zwykłe kliknięcie wybiera cały napis (wszystkie litery), Shift + klik odznacza / dodaje pojedynczą literę."""
        try:
            plane = src['plane']
            key = self._plane_key(plane)
            found = self._drawn_sketches().get(key)
            hit = self.view._plane_hit(plane, x, y)
            if not found or hit is None:
                return src
            plane, bodies = found
            texts = [b for b in bodies if hist.text_group_of(b.id)]
            for group in dict.fromkeys(hist.text_group_of(b.id) for b in texts):
                material = hist.material_faces([b for b in texts if hist.text_group_of(b.id) == group])
                if not any(kernel.face_contains(m, hit[1]) for m in material):
                    continue
                cluster = ('text', group, key)
                letters = [f for f in self._regions_for(key, plane, bodies) if any(kernel.face_contains(m, hist._inner_point(f)) for m in material)]
                src = dict(src, letters=True, cluster=cluster)
                others = [dict(kind='region', id=None, face=f, wire=f.outerWire(), plane=plane, normal=src['normal'], center=f.Center().toTuple(), letters=True, cluster=cluster)
                          for f in letters if not np.allclose(f.Center().toTuple(), src['center'], atol=1e-6)]
                return dict(src, siblings=others)
        except Exception:
            pass
        return src

    def pick_profile(self, x, y, shift=False):
        try:
            src = self._profile_at(x, y)
        except Exception as exc:
            self.toast(str(exc) or 'Nie udało się wybrać profilu.')
            return
        if src is None:
            self.toast('Kliknij zamknięty profil szkicu albo płaską ścianę bryły.')
            return
        group = [src, *src.get('siblings', ())]
        had = bool(self.ex_profiles)
        # kliknięcie dodaje kolejny profil (bez Shift), Shift + klik odznacza pomyłkowo wybrany
        if shift and src.get('letters'):
            group = [src]             # Shift na literze: tylko ta litera
        dup = [p for p in self.ex_profiles if (p.get('cluster') is not None and p.get('cluster') == src.get('cluster') and not src.get('letters'))
               or (p['id'] == src['id'] and p['kind'] == src['kind'] and np.allclose(p['center'], src['center'], atol=1e-6))]
        if shift:
            if not dup:
                return
            self.ex_profiles = [p for p in self.ex_profiles if p not in dup]
        elif dup:
            self._ex_pick_order=[*getattr(self,'_ex_pick_order',[]),dup[0]]
            self._place_extrude_handle();return
        else:
            same = lambda p, q: p['id'] == q['id'] and p['kind'] == q['kind'] and np.allclose(p['center'], q['center'], atol=1e-6)
            self.ex_profiles = [*self.ex_profiles, *[g for g in group if not any(same(g, p) for p in self.ex_profiles)]]
        if not shift:self._ex_pick_order=[*getattr(self,'_ex_pick_order',[]),src]
        self._ex_profiles_changed(had)

    def _selected_sketch_profiles(self):
        """Profile szkiców zaznaczonych na liście Obiekty / polu roboczym (np. cała grupa importu DXF / SVG): obszary
        szkicu, które zakrywają, a zamknięte szkice bez obszaru - w całości. Shift + klik odznacza pojedyncze."""
        chosen = [b for b in (self.document.get(i) for i in self.selected) if b is not None and b.kind == 'sketch'
                  and not b.name.startswith(('Konstrukcja', 'Punkt'))]
        if not chosen:
            return []
        out, covered = [], set()
        groups = self._drawn_sketches()
        ids = {b.id for b in chosen}
        for key, (plane, bodies) in groups.items():
            mine = [b for b in bodies if b.id in ids]
            if not mine:
                continue
            frame = kernel.frame_of(plane)
            boxes = []
            for m in mine:
                bb = kernel.bounds(m.shape)
                boxes.append((np.array([bb.xmin, bb.ymin, bb.zmin]) - 1e-6, np.array([bb.xmax, bb.ymax, bb.zmax]) + 1e-6, m))
            tree=BoundsTree([lo for lo,hi,m in boxes],[hi for lo,hi,m in boxes])
            material = {}
            try:
                regions = self._regions_for(key, plane, bodies)
            except Exception:
                regions = []
            for f in regions:
                point = np.asarray(hist._inner_point(f), float)
                for candidate in tree.point(point):
                    low,high,m=boxes[candidate]
                    if (point >= low).all() and (point <= high).all():
                        faces=material.get(m.id)
                        if faces is None:faces=material[m.id]=hist.material_faces([m])
                        if any(kernel.face_contains(face, point) for face in faces):
                            out.append(dict(kind='region', id=None, source_id=m.id, face=f, wire=f.outerWire(), plane=plane, normal=tuple(frame.normal),
                                            center=f.Center().toTuple()))
                            covered.add(m.id)
                            break
        for m in chosen:
            if m.id not in covered and getattr(m.shape, 'IsClosed', lambda: False)():
                out.append(self._sketch_profile(m))
        order={body.id:i for i,body in enumerate(chosen)}
        return sorted(out,key=lambda p:order.get(p.get('source_id',p.get('id')),-1))

    def _ex_profiles_changed(self, shift=False):
        self._hover_key = None
        if not shift:
            self._ex_op_manual = False
            for spin in (self.ex_value, self.ex_second):
                spin.blockSignals(True)
                spin.setValue(10.0)
                spin.blockSignals(False)
        self._auto_extrude_op()
        if not self.ex_profiles:
            self.view.set_selection_meshes(None)
            self.ex_bar.hide()
            self.view.set_preview_mesh(None)
            self.view.set_handles([])
            return
        self._mark_profiles()
        self.ex_bar.show()
        if self.ex_extent.currentData() == 'upto':
            if self.ex_target is not None:
                self._apply_extent_target()
            else:
                self.ex_status.setText(f'Wybrano profili: {len(self.ex_profiles)}. Teraz kliknij płaszczyznę, ścianę, krawędź albo punkt, do którego ma sięgać bryła.')
        else:
            self.ex_status.setText(f'Wybrano profili: {len(self.ex_profiles)}. Przeciągnij strzałkę albo wpisz odległość u góry.')
        self.hint('Przeciągnij pomarańczową strzałkę lub wpisz odległość, potem Zastosuj (Enter).')
        self._focus_ex_value()
        self._layout_overlays()
        self.update_extrude_preview()

    def _focus_ex_value(self):
        """Pole odległości gotowe do pisania: aktywne i z zaznaczoną wartością, więc wpisana liczba od razu ją zastępuje.
        Odłożone do następnego obiegu pętli zdarzeń - zwolnienie przycisku myszy na widoku 3D oddaje mu fokus zaraz po kliknięciu."""
        def go():
            if self.mode == 'extrude' and self.ex_bar.isVisible():
                self.ex_value.setFocus(Qt.OtherFocusReason)
                self.ex_value.selectAll()
        go()
        QTimer.singleShot(0, go)

    def _mark_profiles(self):
        profiles=tuple(self.ex_profiles)
        def compute():
            meshes=[]
            for src in profiles:
                face=src.get('face') or profile_face(src['wire'])
                if face is not None:meshes.append(kernel.display_mesh(face))
            return _merge_meshes(meshes) if meshes else None
        if len(profiles)<12:
            mesh=compute();self.view.set_selection_meshes([mesh] if mesh is not None else None)
        else:
            self.view.set_selection_meshes(None)
            def show(mesh,error):
                current=self.ex_profiles
                if self.mode=='extrude' and not error and len(current)==len(profiles) and all(a is b for a,b in zip(current,profiles)):
                    self.view.set_selection_meshes([mesh] if mesh is not None else None)
            self.run_preview('profile_selection',compute,show)

    # ----- wyciągnięcie do elementu: wysokość wskazanej płaszczyzny, ściany, krawędzi albo punktu -----
    def _ex_extent_changed(self, *_):
        upto = self.ex_extent.currentData() == 'upto'
        if upto and self.ex_dir.currentData() != 'one':
            self.ex_dir.setCurrentIndex(0)        # bryła sięga do elementu po jednej stronie profilu
        self.ex_dir_label.setVisible(not upto)
        self.ex_dir.setVisible(not upto)
        self.ex_target = None
        self._ex_join_scope_update()
        self.ex_target_label.hide()
        self.view.hover_vertex = None
        self.view._set_hover_edge(None)
        self.view.overlay.update()
        if self.mode != 'extrude':
            return
        if not self.ex_profiles:
            self.ex_status.setText('Kliknij zamknięty profil szkicu lub płaską ścianę bryły.')
        elif upto:
            self.ex_status.setText('Kliknij płaszczyznę, ścianę, krawędź albo punkt, do którego ma sięgać bryła.')
        else:
            self.ex_status.setText(f'Wybrano profili: {len(self.ex_profiles)}. Przeciągnij strzałkę albo wpisz odległość u góry.')
        self.ex_bar.adjustSize()

    @staticmethod
    def _edge_point_near(view, points, x, y):
        """Punkt krawędzi (łamanej z siatki) najbliższy kursorowi na ekranie."""
        points = np.asarray(points, float)
        if getattr(view,'section_plane',None) is not None:
            from .sectionview import clip_segments
            pairs=clip_segments(np.stack((points[:-1],points[1:]),axis=1).reshape(-1,3),view.section_plane).reshape(-1,2,3)
            if not len(pairs):return None
            starts,ends=pairs[:,0],pairs[:,1]
            points=np.stack((starts,ends),axis=1).reshape(-1,3)
            xy,_,w=view.project_points(points)
            a,b=xy[0::2],xy[1::2];wa,wb=w[0::2],w[1::2]
        else:
            xy,_,w=view.project_points(points)
            starts,ends=points[:-1],points[1:]
            a,b=xy[:-1],xy[1:];wa,wb=w[:-1],w[1:]
        if len(xy) != len(points) or len(points) < 2:
            return points[0] if len(points) else None
        delta = b - a
        t = np.clip(((np.array([x, y]) - a) * delta).sum(axis=1) / np.maximum((delta * delta).sum(axis=1), 1e-12), 0, 1)
        dist = np.linalg.norm(a + delta * t[:, None] - [x, y], axis=1)
        dist[(wa <= 0) | (wb <= 0)] = np.inf
        j = int(np.argmin(dist))
        den=wb[j]*(1-t[j])+wa[j]*t[j]
        parameter=t[j]*wa[j]/den if abs(den)>1e-12 else t[j]
        return starts[j]+(ends[j]-starts[j])*parameter

    def _extent_target_at(self, x, y):
        """Element wskazujący wysokość wyciągnięcia: punkt (wierzchołek), krawędź, ściana bryły albo płaszczyzna środkowa.
        Zwraca dict(kind, point, label, edge) albo None. Wysokość to rzut punktu na normalną profilu."""
        if not self.ex_profiles:
            return None
        n = np.array(self.ex_profiles[0]['normal'], float)
        n = n / max(np.linalg.norm(n), 1e-12)
        vertex = self.view.nearest_vertex(x, y, solids_only=False)
        if vertex is not None:
            return dict(kind='vertex', point=np.asarray(vertex[1], float), label='punkt', edge=None, body=vertex[0])
        edge = self.view.nearest_edge(x, y)
        if edge is not None:
            body = next((b for b in self.view.bodies if b.id == edge[0]), None)
            pts = body.mesh.edges.get(edge[1]) if body is not None and body.mesh is not None else None
            if pts is not None and len(pts):
                pts = np.asarray(pts, float)
                heights = pts @ n
                if float(heights.max() - heights.min()) < 1e-4:     # krawędź równoległa do profilu: jedna wysokość
                    point = pts[0]
                else:
                    point = self._edge_point_near(self.view, pts, x, y)
                if point is not None:
                    return dict(kind='edge', point=np.asarray(point, float), label='krawędź', edge=edge, body=edge[0])
        hit = self.view.pick_face(x, y)
        if hit is not None:
            point = np.asarray(hit[2], float)
            body = self.document.get(hit[0])
            if body is not None and body.kind == 'solid':
                try:
                    face, normal = self.view.face_at(body,hit, curved=True)
                    if abs(float(np.dot(np.asarray(normal, float), n))) > 1 - 1e-6:   # ściana równoległa do profilu: dokładna wysokość z jej środka
                        point = np.asarray(face.Center().toTuple(), float)
                except Exception:
                    pass
            return dict(kind='face', point=point, label='ściana', edge=None, body=hit[0])
        if self._planes_visible:
            name = self.view.plane_at(x, y)
            if name:
                frame = kernel.frame_of(name)
                hitp = self.view._plane_hit(name, x, y)
                point = np.asarray(frame.origin, float) if abs(float(np.dot(np.asarray(frame.normal, float), n))) > 1 - 1e-6 or hitp is None else np.asarray(hitp[1], float)
                return dict(kind='plane', point=point, label=f'płaszczyzna {name}', edge=None, body=None)
        return None

    def _ex_join_scope_update(self):
        shown=self.ex_extent.currentData()=='upto' and self.ex_op.currentData()=='join'
        self.ex_join_label.setVisible(shown);self.ex_join_scope.setVisible(shown)
        target=self.ex_target
        enabled=bool(target and target.get('body') and self.document.get(target['body']) and self.document.get(target['body']).kind=='solid')
        self.ex_join_scope._buttons[1].setEnabled(enabled)
        if not enabled and self.ex_join_scope.currentData()=='target':
            self.ex_join_scope.blockSignals(True);self.ex_join_scope.setCurrentIndex(0);self.ex_join_scope.blockSignals(False)

    def _extent_skip(self):
        """Bryła wskazana przy wyciąganiu „Do elementu” wyznacza tylko wysokość: Połącz nie dokleja do niej wyciągnięcia
        (Wytnij i Wspólna działają na wszystkich bryłach, przez które przechodzi narzędzie, także na niej).
        Wyjątek: profil leży na tej samej bryle (np. wyrównanie schodka do wyższej ściany tej bryły) - wtedy to jej własna operacja."""
        target = self.ex_target
        body = self.document.get(target.get('body')) if target and target.get('body') else None
        if body is None or body.kind != 'solid':
            return []
        for src in self.ex_profiles:
            if src.get('kind') in ('face', 'cyl') and src.get('id') == body.id:
                return []
            try:
                face = src.get('face') or profile_face(src['wire'])
                point = hist._inner_point(face) if face is not None else np.array(src['center'], float)
                if kernel.point_state(body.shape, point) != 'out':
                    return []
            except Exception:
                return []
        return [body.id]

    def _extent_distance(self, target):
        src = self.ex_profiles[0]
        n = np.array(src['normal'], float)
        n = n / max(np.linalg.norm(n), 1e-12)
        return float(np.dot(np.asarray(target['point'], float) - np.array(src['center'], float), n))

    def _hover_extent_target(self, x, y):
        try:
            target = self._extent_target_at(x, y)
        except Exception:
            target = None
        self.view._set_hover_edge(target['edge'] if target and target['edge'] else None)
        shown = target or self.ex_target       # bez elementu pod kursorem znacznik zostaje na wybranym celu
        self.view.hover_vertex = shown['point'] if shown else None
        self.view.overlay.update()

    def pick_extent_target(self, x, y):
        try:
            target = self._extent_target_at(x, y)
        except Exception as exc:
            self.toast(str(exc) or 'Nie udało się wskazać elementu.')
            return
        if target is None:
            self.toast('Kliknij płaszczyznę, ścianę, krawędź albo punkt, do którego ma sięgać bryła.')
            return
        if abs(self._extent_distance(target)) < 1e-4:
            self.toast('Ten element leży na wysokości profilu - wskaż inny.')
            return
        self.ex_target = target
        self._ex_join_scope_update()
        self._apply_extent_target()

    def _apply_extent_target(self):
        if self.ex_target is None or not self.ex_profiles:
            return
        d = round(self._extent_distance(self.ex_target), 4)
        if abs(d) < 1e-4:
            self.ex_target_label.hide()
            self.ex_status.setText('Wskazany element leży na wysokości profilu - wskaż inny.')
            return
        self._ex_from_target = True
        try:
            self.ex_value.setValue(d)
        finally:
            self._ex_from_target = False
        self.ex_target_label.setText(f'do: {self.ex_target["label"]}')
        self.ex_target_label.show()
        self.ex_bar.adjustSize()
        self._layout_overlays()
        self.view.hover_vertex = self.ex_target['point']
        self.view.overlay.update()
        self.ex_status.setText(f'Wyciągnięcie do elementu ({self.ex_target["label"]}): {d:g} mm. Kliknij inny element, aby zmienić, potem Zastosuj (Enter).')
        self._focus_ex_value()

    def _ex_dir_changed(self, *_):
        two = self.ex_dir.currentData() == 'two'
        self.ex_second_label.setVisible(two)
        self.ex_second.setVisible(two)
        self.ex_bar.adjustSize()
        self._timers['extrude'].start()

    def _cube_roll(self, degrees):
        """Strzałki obrotu przy kostce: obraz obraca się o 90° wokół osi patrzenia (np. żeby ustawić szkic tak, jak trzeba)."""
        self.view.set_roll(round((self.view.roll() + degrees) / 90.0) * 90.0)
        self.cube.update()

    def _cube_rotate(self, daz, delev):
        """Strzałki kostki: przerzucenie widoku o 90° w kierunku strzałki na ekranie (także po obróceniu obrazu)."""
        right, up, back = self.view.screen_axes()

        def snap(v):
            v = np.asarray(v, float)
            k = int(np.argmax(np.abs(v)))
            if abs(v[k]) > .9:                       # prawie wzdłuż osi: dokładnie na oś (widok ściany kostki)
                out = np.zeros(3)
                out[k] = np.sign(v[k])
                return out
            return v

        back, up, right = snap(back), snap(up), snap(right)
        if daz:
            a = math.radians(daz)
            back = back * math.cos(a) + right * math.sin(a)
        if delev:
            back, up = (up, -back) if delev > 0 else (-up, back)
        self.view.orient(snap(back), snap(up))
        self.cube.update()

    def _auto_extrude_op(self):
        """Wciąganie w bryłę = wycinanie, na zewnątrz = połączenie (dopóki użytkownik sam nie wybrał operacji)."""
        if getattr(self, '_ex_op_manual', False) or len({p.get('cluster', id(p)) for p in self.ex_profiles}) != 1 or self.ex_dir.currentData() != 'one':
            return
        src = self.ex_profiles[0]
        value = self.ex_value.value()
        if abs(value) < 1e-6:
            return
        # położenie profilu względem brył zależy tylko od profilu, modelu i strony (+/-), nie od samej wartości:
        # liczone raz, a nie przy każdej zmianie odległości
        key = (id(src), self.document._revision, value > 0)
        cache = self.__dict__.setdefault('_ex_side_cache', {})
        hit = cache.get(key)
        if hit is None:
            n = np.array(src['normal'], float)
            c = np.array(src['center'], float)
            solids = [b for b in self.document.bodies if b.kind == 'solid']
            touching = src.get('kind') in ('face', 'cyl')
            sample = c + n * (.05 if value > 0 else -.05)
            inside = False
            try:
                if not touching:
                    touching = any(kernel.point_state(b.shape, c) != 'out' for b in solids)
                inside = touching and any(kernel.point_state(b.shape, sample) == 'in' for b in solids)
                if not touching and src.get('plane') is not None and self._gap_pad(src) > 0:
                    touching, inside = True, value < 0      # szkic na skręconej ścianie: między nim a bryłą jest przerwa, ale to nadal jej ściana
            except Exception:
                return
            if len(cache) > 64:
                cache.clear()
            cache[key] = hit = (src, touching, inside)
        touching, inside = hit[1], hit[2]
        want = 'new' if not touching else ('cut' if inside else 'join')
        if self.ex_op.currentData() != want:
            self._ex_auto = True
            try:
                self.ex_op.setCurrentIndex(self.ex_op._data.index(want))
            finally:
                self._ex_auto = False

    def _protected(self):
        """Bryły ukryte na liście obiektów: żadna operacja ich nie zmienia (wycięcie przechodzące przez ukrytą bryłę jej nie tnie)."""
        return {b.id for b in self.document.bodies if b.id in self.hidden_ids and b.kind == 'solid'}

    def _new_folder(self, profiles, spent, count, op, label):
        """Grupa na liście obiektów dla kilku nowych brył z jednej operacji (napis, szyk szkiców, kilka profili)."""
        if op != 'new' or count < 2:
            return ''
        names = [self.document.get(i).name for i in spent if self.document.get(i) is not None]
        folders = [self.document.get(i).folder for i in spent if self.document.get(i) is not None and self.document.get(i).folder]
        for p in profiles:
            b = self.document.get(p.get('id')) if p.get('id') else None
            if b is not None:
                names.append(b.name)
                if b.folder:
                    folders.append(b.folder)
        if folders:
            base = folders[0]
        elif names:
            base = names[0].split(' — szyk')[0]
        else:
            base = label
        return f'{base} — bryły'

    def _gap_pad(self, src):
        """Odstęp szkicu od skręconej ściany (hist.gap_pad) - zapamiętany dla profilu i stanu modelu (to drogie liczenie)."""
        key = (id(src), self.document._revision)
        cache = self.__dict__.setdefault('_gap_cache', {})
        hit = cache.get(key)
        if hit is None:
            if len(cache) > 64:
                cache.clear()
            cache[key] = hit = (src, hist.gap_pad(self.document.bodies, src))
        return hit[1]

    def _ex_op_user_changed(self):
        self._ex_join_scope_update()
        if not getattr(self, '_ex_auto', False):
            self._ex_op_manual = True

    def _ex_value_changed(self):
        if self.ex_target is not None and not getattr(self, '_ex_from_target', False):
            self.ex_target = None        # odległość zmieniona ręcznie: wyciągnięcie nie jest już związane ze wskazanym elementem
            self._ex_join_scope_update()
            self.ex_target_label.hide()
            self.view.hover_vertex = None
            self.view.overlay.update()
        self._auto_extrude_op()
        self._timers['extrude'].start()
        if self._hv is None:
            self._place_extrude_handle()

    def _place_extrude_handle(self):
        if self.mode != 'extrude' or not self.ex_profiles:
            self.view.set_handles([])
            return
        order=[p for p in getattr(self,'_ex_pick_order',[]) if any(p is q for q in self.ex_profiles)]
        self._ex_pick_order=order
        src=order[-1] if order else self.ex_profiles[-1]
        n = np.array(src['normal'], float)
        c = np.array(src['center'], float)
        d = self.ex_value.value()
        mode = self.ex_dir.currentData()
        sign = 1.0 if d >= 0 else -1.0
        handles = [dict(id='ex', start=c, tip=c + n * (d / 2 if mode == 'symmetric' else d), dir=n, color=(.94, .6, .13, 1), label='+')]
        if mode == 'two':
            d2 = self.ex_second.value()
            handles.append(dict(id='ex2', start=c, tip=c - n * d2, dir=-n, color=(.11, .51, .81, 1), label='−'))
        self.view.set_handles(handles)
    def _make_tools(self):
        """Funkcje budujące bryły-narzędzia (po jednej na profil); bezpieczne dla wątku roboczego."""
        if not self.ex_profiles:
            raise kernel.CadError('Wybierz profil szkicu lub ścianę.')
        d1, d2 = self.ex_value.value(), self.ex_second.value()
        mode = self.ex_dir.currentData()
        out = []
        for src in self.ex_profiles:
            wire, normal, plane, face = src['wire'], src['normal'], src['plane'], src.get('face')
            if src.get('kind') == 'cyl':          # ściana walcowa: zmiana promienia o d1 (+ dodaje, - wycina materiał)
                out.append(partial(kernel.cylinder_offset_tool, src['cyl'], d1))
                continue
            if face is not None:
                out.append(partial(kernel.extrude_face, face, normal, d1, d2 if mode == 'two' else 0.0, mode == 'symmetric'))
            elif mode == 'two':
                out.append(partial(kernel.extrude_dir, wire, normal, d1, d2))
            elif plane is not None:
                pad = self._gap_pad(src) if mode == 'one' else 0.0
                if pad > 0:      # szkic na płaszczyźnie przylegającej do skręconej ściany: narzędzie cofnięte o odstęp, żeby nie została przerwa
                    out.append(partial(kernel.extrude_dir, wire, normal, d1, -pad if d1 < 0 else pad))
                else:
                    out.append(partial(kernel.extrude, wire, plane, d1, mode == 'symmetric'))
            else:
                out.append(partial(kernel.extrude_dir, wire, normal, d1, 0.0, mode == 'symmetric'))
        if mode == 'ends':       # oba końce: ta sama odległość na przeciwległej ścianie bryły (np. spód sześcianu dla wskazanej góry)
            bodies = hist.light(self.document.bodies)
            for src in self.ex_profiles:
                out.append(partial(hist.opposite_tool, bodies, src, d1))
        return out

    def update_extrude_preview(self):
        if self.mode != 'extrude' or not self.ex_profiles:
            return
        makers = self._make_tools()
        op = self.ex_op.currentData()
        value_now = self.ex_value.value()

        def compute():          # bryły podglądu liczy proces roboczy - okno w tym czasie działa normalnie
            return _merge_meshes(hist.background(hist.preview_meshes, makers, PREVIEW_TOL))

        def show(mesh, error):
            if self.mode != 'extrude' or not self.ex_profiles:
                return
            if error:
                self.view.set_preview_mesh(None)
                self.ex_status.setText(error)
                self.toast(error)
                return
            self._ex_mesh_value = value_now
            red = op == 'cut'
            color = (.9, .2, .2, .7) if red else ((.3, .75, .5, .72) if op == 'intersect' else PREVIEW_BLUE)
            self.view.set_preview_mesh(mesh, color=color, line_color=(.56, .07, .07, 1) if red else (.14, .3, .45, 1), width=2)
            self.ex_status.setText(f'Wybrano profili: {len(self.ex_profiles)}.')

        self.run_preview('extrude', compute, show)
        if self._hv is None:
            self._place_extrude_handle()
    def _consumed_sketches(self, profiles):
        """Id szkiców, z których powstały wybrane profile (cały szkic albo obszar leżący w jego obrysie)."""
        ids = set()
        for prof in profiles:
            ids |= set(prof.get('hole_ids', ()))      # szkice, które zrobiły otwory w wybranej ścianie
            if prof.get('kind') == 'sketch' and prof.get('id'):
                ids.add(prof['id'])
            elif prof.get('kind') == 'region' and prof.get('face') is not None:
                c = np.array(prof['center'], float)
                for _, bodies in self._drawn_sketches().values():
                    for b in bodies:
                        try:
                            box = kernel.bounds(b.shape)
                            if all(lo - 1e-3 <= v <= hi + 1e-3 for v, lo, hi in zip(c, (box.xmin, box.ymin, box.zmin), (box.xmax, box.ymax, box.zmax))):
                                ids.add(b.id)
                        except Exception:
                            pass
        return ids

    def apply_extrude(self):
        if self.busy or not self.ex_profiles:
            return
        op = self.ex_op.currentData()
        makers = self._make_tools()
        existing = list(self.document.bodies)
        spent = self._consumed_sketches(self.ex_profiles)
        profiles, direction, d1, d2 = list(self.ex_profiles), self.ex_dir.currentData(), self.ex_value.value(), self.ex_second.value()
        out = [uuid.uuid4().hex for _ in makers]
        target = self.ex_target
        upto = None if target is None else dict(kind=target['kind'], point=[float(c) for c in target['point']])
        scope=self.ex_join_scope.currentData() if op=='join' and self.ex_extent.currentData()=='upto' else None
        skip = self._extent_skip() if op == 'join' and scope != 'target' else []      # wycięcie / część wspólna obejmują też bryłę-cel, w którą wchodzi narzędzie
        skip = sorted(set(skip) | self._protected())             # ukrytych brył operacja nie zmienia
        folder = self._new_folder(profiles, spent, len(makers), op, 'Wyciągnięcie')

        def build():
            receivers=hist.extrusion_receivers(existing,profiles,scope,target.get('body') if target else None) if scope else None
            bodies = hist.offloaded(hist.combine, existing, [m() for m in makers], op, spent, out, skip=skip, folder=folder,only=receivers)
            recipe = dict(type='extrude', mode=op, dir=direction, d1=d1, d2=d2, profiles=hist.describe_profiles(profiles, existing), spent=sorted(spent), out=out)
            if receivers is not None:recipe.update(join_to=receivers,join_side=scope)
            if folder:
                recipe['folder'] = folder
            if upto is not None:
                recipe['upto'] = upto      # skąd wzięła się odległość (wyciągnięcie do elementu)
            if skip:
                recipe['skip'] = list(skip)      # bryła-wysokość nie bierze udziału w operacji (także przy przeliczaniu historii)
            return bodies, recipe      # zapis kroku do historii liczy się w tle razem z operacją

        def apply(result):
            bodies, recipe = result
            self.document.pending_op = recipe
            self.document.commit(bodies)
            self._tool_select([bodies[-1].id] if op == 'new' else [])

        self.view.set_preview_mesh(None)
        self.view.set_handles([])
        self.run_operation({'cut': 'Wycięcie', 'join': 'Wyciągnięcie (dodaj)', 'intersect': 'Część wspólna'}.get(op, 'Wyciągnięcie'), build, apply, after=lambda: self.set_mode(None))

    # =====================================================================
    # obrót profilu wokół osi
    # =====================================================================
    @staticmethod
    def _face_points(face):
        pts = [v.toTuple() for v in face.Vertices()]
        for edge in face.Edges():
            pts += [edge.positionAt(t).toTuple() for t in (.25, .5, .75)]
        return np.array(pts, float)

    def pick_revolve(self, x, y, shift=False):
        if self.rev_profiles and self.rev_axis.currentData() == 'line' and self.rev_line is None:
            self._rev_pick_axis(x, y)
            return
        try:
            src = self._profile_at(x, y)
        except Exception as exc:
            self.toast(str(exc) or 'Nie udało się wybrać profilu.')
            return
        if src is not None and src.get('kind') == 'cyl':
            src = None
        if src is None:
            self.toast('Kliknij zamknięty profil szkicu albo płaską ścianę bryły.')
            return
        group = [src, *src.get('siblings', ())]
        if shift:
            if src.get('letters'):
                group = [src]
            dup = [p for p in self.rev_profiles if (p.get('cluster') is not None and p.get('cluster') == src.get('cluster') and not src.get('letters'))
                   or (p['id'] == src['id'] and p['kind'] == src['kind'] and np.allclose(p['center'], src['center'], atol=1e-6))]
            self.rev_profiles = [p for p in self.rev_profiles if p not in dup] if dup else [*self.rev_profiles, *group]
        else:
            self.rev_profiles = group
            self.rev_line = None
        self._hover_key = None
        self.view.set_preview_mesh(None)
        self._rev_auto_axis()
        self._rev_update()

    def _rev_pick_axis(self, x, y):
        hit = self.view.nearest_edge(x, y)
        body = self.document.get(hit[0]) if hit else None
        points = body.mesh.edges.get(hit[1]) if body is not None and body.mesh is not None else None
        if points is None or len(points) < 2:
            self.toast('Kliknij prostą linię szkicu lub prostą krawędź bryły.')
            return
        pts = np.asarray(points, float)
        d = pts[-1] - pts[0]
        length = float(np.linalg.norm(d))
        if length < 1e-6 or float(np.max(np.linalg.norm(np.cross(pts - pts[0], d / length), axis=1))) > 1e-3 * max(1.0, length):
            self.toast('Oś musi być prostą linią.')
            return
        self.rev_line = dict(k='line', p=[float(c) for c in pts[0]], d=[float(c) / length for c in d])
        self.view._set_hover_edge(None)
        self._rev_update()

    def _rev_auto_axis(self):
        """Dobiera oś, której profil nie przecina (preferuje pionową), dopóki użytkownik sam nie wybrał osi."""
        if self._rev_manual or not self.rev_profiles:
            return
        try:
            origin, u, v, _ = hist.profile_frame(self.rev_profiles[0])
            pts = self._face_points(self.rev_profiles[0].get('face') or profile_face(self.rev_profiles[0]['wire']))
            cu, cv = (pts - origin) @ u, (pts - origin) @ v
            ok = lambda c: c.min() >= -1e-4 or c.max() <= 1e-4
            choice = 'v' if ok(cu) else ('u' if ok(cv) else None)
        except Exception:
            choice = None
        if choice and choice != self.rev_axis.currentData():
            self.rev_axis.blockSignals(True)
            self.rev_axis.setCurrentIndex(['u', 'v', 'line'].index(choice))
            self.rev_axis.blockSignals(False)

    def _rev_axis_changed(self, *_):
        self._rev_manual = True
        self.rev_line = None
        self._rev_update()

    def _rev_axis_spec(self):
        kind = self.rev_axis.currentData()
        if kind == 'line':
            if self.rev_line is None:
                raise kernel.CadError('Wskaż linię szkicu lub krawędź bryły jako oś obrotu.')
            return dict(self.rev_line)
        return dict(k=kind)

    def _rev_update(self):
        """Odświeża podpowiedzi kroków, zaznaczenie profilu i osi oraz podgląd bryły."""
        have = bool(self.rev_profiles)
        line = self.rev_axis.currentData() == 'line'
        self.rev_step1.set_state('done' if have else 'active', f'Wybrano: {len(self.rev_profiles)}' if have else 'Kliknij profil lub ścianę')
        if not have:
            self.rev_step2.set_state('pending', 'Najpierw wybierz profil')
        elif line and self.rev_line is None:
            self.rev_step2.set_state('active', 'Kliknij linię lub krawędź')
        else:
            self.rev_step2.set_state('done', {'u': 'Oś pozioma szkicu', 'v': 'Oś pionowa szkicu', 'line': 'Wskazana linia'}[self.rev_axis.currentData()])
        self.rev_status.setText('Kliknij zamknięty profil szkicu lub płaską ścianę bryły.' if not have else
                                ('Kliknij linię szkicu lub krawędź bryły jako oś.' if line and self.rev_line is None else f'Profili: {len(self.rev_profiles)}. Enter zatwierdza.'))
        self._rev_mark()
        if not have:
            self.view.set_preview_mesh(None)
            return
        self._timers['revolve'].start()

    def _rev_mark(self):
        meshes = []
        for src in self.rev_profiles:
            try:
                face = src.get('face') or profile_face(src['wire'])
                if face is not None:
                    meshes.append(kernel.display_mesh(face))
            except Exception:
                pass
        try:
            if meshes and self.rev_profiles and not (self.rev_axis.currentData() == 'line' and self.rev_line is None):
                src = self.rev_profiles[0]
                point, direction = hist.resolve_axis(self._rev_axis_spec(), src)
                pts = self._face_points(src.get('face') or profile_face(src['wire']))
                size = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0))) or 10.0
                mid = point + direction * float(((pts.mean(axis=0) - point) @ direction))
                line = np.array([mid - direction * size * .9, mid + direction * size * .9], np.float32)
                meshes.append(kernel.DisplayMesh(np.zeros((0, 3), np.float32), np.zeros((0, 3), np.uint32), {0: line}, tuple(float(c) for c in mid), 1.0))
        except Exception:
            pass
        self.view.set_selection_meshes(meshes or None)

    def _rev_tools(self):
        if not self.rev_profiles:
            raise kernel.CadError('Wybierz profil szkicu lub ścianę.')
        axis, angle = self._rev_axis_spec(), self.rev_angle.value()
        return [partial(hist.make_revolve, src, axis, angle) for src in self.rev_profiles]

    def update_revolve_preview(self):
        if self.mode != 'revolve' or not self.rev_profiles:
            return
        try:
            makers = self._rev_tools()
        except kernel.CadError:
            self.view.set_preview_mesh(None)
            return
        op = self.rev_op.currentData()

        def compute():          # bryły podglądu liczy proces roboczy - okno w tym czasie działa normalnie
            return _merge_meshes(hist.background(hist.preview_meshes, makers, PREVIEW_TOL))

        def show(mesh, error):
            if self.mode != 'revolve' or not self.rev_profiles:
                return
            if error:
                self.view.set_preview_mesh(None)
                self.rev_status.setText(error)
                return
            red = op == 'cut'
            color = (.9, .2, .2, .7) if red else ((.3, .75, .5, .72) if op == 'intersect' else PREVIEW_BLUE)
            self.view.set_preview_mesh(mesh, color=color, line_color=(.56, .07, .07, 1) if red else (.14, .3, .45, 1), width=2)
            self.rev_status.setText(f'Profili: {len(self.rev_profiles)}. Enter zatwierdza.')

        self.run_preview('revolve', compute, show)

    def apply_revolve(self):
        if self.busy or not self.rev_profiles:
            return
        try:
            makers = self._rev_tools()
            axis = self._rev_axis_spec()
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        op = self.rev_op.currentData()
        existing = list(self.document.bodies)
        spent = self._consumed_sketches(self.rev_profiles)
        profiles, angle = list(self.rev_profiles), self.rev_angle.value()
        out = [uuid.uuid4().hex for _ in makers]

        skip = sorted(self._protected())
        folder = self._new_folder(profiles, spent, len(makers), op, 'Obrót')

        def build():
            bodies = hist.offloaded(hist.combine, existing, [m() for m in makers], op, spent, out, 'Obrót', skip=skip, folder=folder)
            recipe = dict(type='revolve', mode=op, axis=axis, angle=angle, profiles=hist.describe_profiles(profiles, existing), spent=sorted(spent), out=out)
            if skip:
                recipe['skip'] = skip
            if folder:
                recipe['folder'] = folder
            return bodies, recipe

        def apply(result):
            bodies, recipe = result
            self.document.pending_op = recipe
            self.document.commit(bodies)
            self._tool_select([bodies[-1].id] if op == 'new' else [])

        self.view.set_preview_mesh(None)
        label = {'new': 'Obrót', 'join': 'Obrót (dodaj)', 'cut': 'Obrót (wytnij)', 'intersect': 'Obrót (część wspólna)'}[op]
        self.run_operation(label, build, apply, after=lambda: self.set_mode(None))

    # =====================================================================
    # zakładki paska narzędzi
    # =====================================================================
    def set_tab(self, name):
        if name not in TABS or name == self._tab and self.tab_buttons[name].isChecked():
            return
        self._tab = name
        self.tab_buttons[name].setChecked(True)
        self._layout_overlays()

    # ---------- Ulubione: Przybornik i wybrane narzędzia ----------
    def _tab_tools(self, name):
        """Przyciski zakładki; Ulubione = Przybornik i wybrane narzędzia w ustalonej kolejności."""
        if name == 'Ulubione':
            return ['toolbox', *[k for k in getattr(self, 'favorites', []) if k in FAVORITE_TOOLS]]
        return TABS[name]

    def _tool_name(self, key):
        return self.tools[key].toolTip().split(' — ')[0]

    def _load_favorites(self):
        values = self._read_settings('favorites') or {}
        keys = values.get('tools') if isinstance(values, dict) else None
        return [k for k in (keys or []) if k in FAVORITE_TOOLS and k in self.tools][:len(FAVORITE_TOOLS)]

    def set_favorites(self, keys, save=True):
        """Zapisuje wybrane narzędzia (kolejność = kolejność na pasku Ulubionych, zaraz po Pliku i Przyborniku)."""
        seen = []
        for k in keys:
            if k in FAVORITE_TOOLS and k not in seen:
                seen.append(k)
        self.favorites = seen
        if save:
            self._write_settings('favorites', {'tools': seen})
        self.tab_buttons['Ulubione'].setToolTip('Zakładka narzędzi: ' + ', '.join(self._tool_name(k) for k in self._tab_tools('Ulubione')))
        self._layout_overlays()

    def open_toolbox(self):
        from .toolbox import ToolboxDialog
        items = [(key, self._tool_name(key), TAB_OF[key], self.tools[key].icon()) for key in FAVORITE_TOOLS]
        self.toolbox_dialog = ToolboxDialog(self, items, self.favorites, self.set_favorites)
        self.toolbox_dialog.open()
        return self.toolbox_dialog

    # =====================================================================
    # pomiary
    # =====================================================================
    def _measure_reset(self):
        self.ms_points = []
        self.ms_refs=[];self.ms_angle_refs=[];self._measure_hover_key=None
        self.view.measure_labels=[];self.view.measure_live=None
        self.view.hover_vertex=None;self.view.snap_marker=None;self.view._set_hover_edge(None)
        self.view.overlay.update()
        self.view.set_selection_meshes(None)
        self.view.set_preview_mesh(None)
        if self.mode in MEASURE_MODES:
            self.ms_status[self.mode].setText('Wskaż obiekt na polu roboczym.')
            self.ms_hover_label[self.mode].setText('Najedź na element, aby zobaczyć, co zostanie zmierzone.')
            self._measure_panel_fit()

    def _measure_show(self, text, meshes=None):
        refs=getattr(self,'ms_refs',[])
        if refs:text+='<br><small>'+html_escape(' → '.join(r['label'] for r in refs))+'</small>'
        self.ms_status[self.mode].setText(text)
        self._measure_panel_fit()
        self.view.set_selection_meshes(meshes or None, color=(.3, .8, .5, .5), line_color=(.05, .75, .25, 1))

    def _measure_panel_fit(self):
        """Wrap the complete result above a fixed footer, with scrolling on short screens."""
        panel=self.ms_panels.get(self.mode)
        if panel is None:return
        area,body=panel.scroll
        width=max(100,panel.width()-52)
        for label in body.findChildren(QLabel):
            policy=label.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Ignored)
            policy.setVerticalPolicy(QSizePolicy.Minimum)
            label.setSizePolicy(policy)
            label.setWordWrap(True)
            key=(label.text(),label.font().toString(),label.styleSheet(),width)
            if key!=getattr(label,'_measure_size_key',None):
                # heightForWidth respects the previous minimum: clear it before
                # measuring, otherwise every hover grows the label by the padding.
                label.setMinimumHeight(0)
                label.setMinimumHeight(max(label.fontMetrics().height()+4,label.heightForWidth(width)+4))
                label._measure_size_key=key
        body.layout().setAlignment(Qt.AlignTop)
        body.layout().invalidate()
        # With an ignored horizontal size hint, QWidget.sizeHint() may wrap
        # at a tiny width. Measure the column at its actual fixed panel width.
        natural=body.layout().heightForWidth(width+12)
        panel._measure_body_height=max(0,natural) if natural>=0 else body.layout().sizeHint().height()
        body.setMinimumHeight(panel._measure_body_height);body.updateGeometry()
        self._fit_panel(panel,88+TOOLS_TOP-18)

    def _measure_back(self):
        """One right click removes only the last reference; geometry/history stay intact."""
        self.view.hover_vertex=None;self.view.snap_marker=None
        self.view.measure_live=None;self.view._set_hover_edge(None)
        self.view.set_preview_mesh(None);self._measure_hover_key=None
        if self.mode=='mangle' and self.ms_angle_kind.currentData()!='points':
            self.ms_angle_refs=self.ms_angle_refs[:-1]
            if not self.ms_angle_refs:self._measure_reset()
            else:self._measure_angle_refs_update(self.ms_angle_refs)
        elif self.mode in ('mdist','mangle') and self.ms_points:
            self.ms_points.pop();self.ms_refs=self.ms_refs[:-1]
            self.view.measure_labels=[(r['point'],str(i+1)) for i,r in enumerate(self.ms_refs)]
            if self.ms_points:self._measure_points_update()
            else:self._measure_reset()
        else:self._measure_reset()
        self.view.overlay.update()

    def _measure_candidate(self,x,y):
        mode=self.mode
        kind=self.ms_angle_kind.currentData() if mode=='mangle' else 'points'
        if mode in ('mdist','mangle') and kind=='points':
            vertex=self.view.nearest_vertex(x,y,solids_only=False)
            if vertex:
                body=self.document.get(vertex[0])
                return dict(kind='vertex',id=vertex[0],point=np.asarray(vertex[1]),label=f'Wierzchołek — {body.name if body else "obiekt"}')
        if mode=='mrad' or (mode in ('mdist','mangle') and kind!='faces'):
            hit=self.view.nearest_edge(x,y)
            body=self.document.get(hit[0]) if hit else None
            if body is not None:
                edge=body.shape.Edges()[hit[1]]
                if mode=='mangle' and kind=='edges' and edge.geomType()!='LINE':return None
                points=body.mesh.edges[hit[1]]
                point=self._edge_point_near(self.view,points,x,y)
                if point is None:return None
                point=measurement.on_edge(edge,point)
                if not self.view.section_contains(point):return None
                label=f'Krawędź {hit[1]+1} — {body.name}'
                if mode in ('mdist','mangle') and kind=='points':
                    a,b=np.asarray(edge.startPoint().toTuple()),np.asarray(edge.endPoint().toTuple())
                    mid=np.asarray(edge.positionAt(.5).toTuple())
                    xy=self.view.project_one(mid)
                    if xy and np.linalg.norm(np.asarray(xy)-[x,y])<9 and self.view.section_contains(mid) and self.view._visible_point(mid):
                        point=mid;label=f'Środek krawędzi {hit[1]+1} — {body.name}'
                return dict(kind='edge',id=body.id,edge=hit[1],point=point,label=label)
            if kind=='edges' or mode=='mrad':return None
        hit=self.view.pick_face(x,y)
        body=self.document.get(hit[0]) if hit else None
        if body is not None:
            if mode=='mprops':return dict(kind='body',id=body.id,point=np.asarray(hit[2]),label=f'Cały obiekt — {body.name}')
            if body.kind=='sketch':
                if kind=='faces':return None
                face=profile_face(body.shape)
                if face is None:return None
                normal=kernel.frame_of(body.plane).normal
            else:face,normal=self.view.face_at(body,hit,curved=kind!='faces')
            point=measurement.on_shape(face,hit[2])
            if not self.view.section_contains(point):return None
            name='Punkt na szkicu' if body.kind=='sketch' else 'Płaska ściana' if kind=='faces' else 'Punkt na powierzchni'
            return dict(kind='face',id=body.id,face=face,normal=np.asarray(normal),point=point,label=f'{name} — {body.name}')
        if mode=='mprops':
            bid=self.view.pick_body(x,y) if self.view.section_plane is not None else None
            if bid is None:bid=self.view.pick_profile(x,y)
            edge=self.view.nearest_edge(x,y) if bid is None else None
            body=self.document.get(bid or (edge[0] if edge else ''))
            if body is not None:return dict(kind='body',id=body.id,point=np.asarray(body.shape.Center().toTuple()),label=f'Cały obiekt — {body.name}')
        return None

    def _measure_hover(self,x,y):
        old_text=self.ms_hover_label[self.mode].text()
        try:ref=self._measure_candidate(x,y)
        except (kernel.CadError,IndexError):ref=None
        self.ms_hover_label[self.mode].setText(ref['label'] if ref else 'Brak elementu. Wskaż widoczny punkt, krawędź lub właściwą ścianę.')
        self.view.hover_vertex=ref['point'] if ref and ref['kind']!='body' else None
        self.view.snap_marker=(self.view.project_one(ref['point']),ref['label']) if ref and self.view.project_one(ref['point']) else None
        self.view._set_hover_edge((ref['id'],ref['edge']) if ref and ref['kind']=='edge' else None)
        key=(ref['id'],ref['face'].hashCode()) if ref and ref['kind']=='face' else (ref['id'],'body') if ref and ref['kind']=='body' else None
        if key!=getattr(self,'_measure_hover_key',None):
            self._measure_hover_key=key
            mesh=kernel.display_mesh(ref['face']) if ref and ref['kind']=='face' else self.document.get(ref['id']).mesh if ref and ref['kind']=='body' else None
            self.view.set_preview_mesh(mesh,color=(.45,.65,.9,.2),line_color=(.15,.45,.85,1))
        self.view.measure_live=None
        if ref and self.mode in ('mdist','mangle') and self.ms_points:
            self.view.measure_live=(self.ms_points[-1],ref['point'])
            if self.mode=='mdist' and len(self.ms_points)==1:
                self.ms_hover_label[self.mode].setText(ref['label']+f' — {np.linalg.norm(ref["point"]-self.ms_points[0]):.3f} mm')
        if self.ms_hover_label[self.mode].text()!=old_text:self._measure_panel_fit()
        self.view.overlay.update()

    def _measure_point(self, x, y):
        try:ref=self._measure_candidate(x,y)
        except (kernel.CadError,IndexError):ref=None
        if ref is not None:
            self.ms_refs.append(ref)
            self.view.measure_labels=[(r['point'],str(i+1)) for i,r in enumerate(self.ms_refs)]
            self.view.measure_live=None
            return np.asarray(ref['point'],float)
        self.toast('Wskaż widoczny narożnik, krawędź albo powierzchnię.');return None

    def _cross(self, point, r=1.5):
        q = np.asarray(point, float)
        return [self._polyline_mesh([q - axis * r, q + axis * r]) for axis in np.eye(3)]

    def pick_measure(self, x, y):
        mode = self.mode
        if mode=='mangle' and self.ms_angle_kind.currentData()!='points':
            self._measure_angle_entities(x,y);return
        if mode in ('mdist', 'mangle'):
            if len(self.ms_points) >= (2 if mode == 'mdist' else 3):
                self.ms_points = [];self.ms_refs=[]
            q = self._measure_point(x, y)
            if q is None:
                return
            self.ms_points.append(q)
            self.view.hover_vertex = None
            self._measure_points_update()
        elif mode == 'mrad':
            self._measure_radius(x, y)
        else:
            self._measure_props(x, y)

    def _measure_points_update(self):
        pts, mode = self.ms_points, self.mode
        meshes = [m for q in pts for m in self._cross(q)]
        if mode == 'mdist':
            if len(pts) == 1:
                self._measure_show('Kliknij drugi punkt.', meshes)
                return
            d = pts[1] - pts[0]
            meshes.append(self._polyline_mesh([pts[0], pts[1]]))
            self._measure_show(f'<b>Odległość: {float(np.linalg.norm(d)):.3f} mm</b><br>ΔX {d[0]:.3f} · ΔY {d[1]:.3f} · ΔZ {d[2]:.3f}<br><small>Kolejne kliknięcie zaczyna nowy pomiar.</small>', meshes)
            return
        if len(pts) == 1:
            self._measure_show('Kliknij wierzchołek kąta.', meshes)
        elif len(pts) == 2:
            meshes.append(self._polyline_mesh(pts))
            self._measure_show('Kliknij koniec drugiego ramienia.', meshes)
        else:
            a, b = pts[0] - pts[1], pts[2] - pts[1]
            if float(np.linalg.norm(a)) < 1e-9 or float(np.linalg.norm(b)) < 1e-9:
                self._measure_show('Punkty nie mogą się pokrywać z wierzchołkiem.', meshes)
                return
            angle = measurement.angle_between(a,b)
            arc=measurement.angle_arc(pts[1],a,b,min(np.linalg.norm(a),np.linalg.norm(b))*.25)
            if arc is not None:meshes.append(self._polyline_mesh(arc))
            meshes.append(self._polyline_mesh([pts[0], pts[1], pts[2]]))
            self._measure_show(f'<b>Kąt: {angle:.2f}°</b><br>Dopełnienie do 180°: {180 - angle:.2f}°<br><small>Kolejne kliknięcie zaczyna nowy pomiar.</small>', meshes)

    def _measure_angle_entities(self,x,y):
        try:
            ref=self._measure_candidate(x,y)
            if ref is None:raise kernel.CadError('Wskaż prostą krawędź albo płaską ścianę zgodnie z wybranym trybem.')
            refs=self.ms_angle_refs
            if len(refs)>=2:refs=[]
            if refs and ref['id']==refs[0]['id'] and ((ref['kind']=='edge' and ref['edge']==refs[0]['edge']) or (ref['kind']=='face' and ref['face'].isSame(refs[0]['face']))):
                raise kernel.CadError('Ten element jest już wybrany. Wskaż drugi.')
            self._measure_angle_refs_update([*refs,ref])
        except kernel.CadError as exc:self.toast(str(exc))

    def _measure_angle_refs_update(self,refs):
        meshes=[];vectors=[]
        for r in refs:
            if r['kind']=='edge':
                b=self.document.get(r['id']);edge=b.shape.Edges()[r['edge']]
                vectors.append(np.asarray(edge.endPoint().toTuple())-np.asarray(edge.startPoint().toTuple()))
                meshes.append(self._polyline_mesh(b.mesh.edges[r['edge']]))
            else:
                vectors.append(r['normal']);meshes.append(kernel.display_mesh(r['face']))
        self.ms_angle_refs=refs
        self.view.measure_labels=[(r['point'],str(i+1)) for i,r in enumerate(refs)]
        names='<br>'.join(html_escape(r['label']) for r in refs)
        if len(refs)==1:self._measure_show('Wskaż drugi element.<br>'+names,meshes);return
        angle=measurement.angle_between(*vectors,unoriented=True)
        a,b=vectors
        if a@b<0:b=-b
        o=(refs[0]['point']+refs[1]['point'])/2
        radius=max(float(np.linalg.norm(refs[0]['point']-refs[1]['point']))*.15,1)
        arc=measurement.angle_arc(o,a,b,radius)
        if arc is not None:meshes.append(self._polyline_mesh(arc))
        self._measure_show(f'<b>Kąt mniejszy: {angle:.2f}°</b><br>Kąt większy: {180-angle:.2f}°<br>{names}<br><small>Kolejne kliknięcie zaczyna nowy pomiar.</small>',meshes)

    def _measure_radius(self, x, y):
        hit = self.view.nearest_edge(x, y)
        body = self.document.get(hit[0]) if hit else None
        points = body.mesh.edges.get(hit[1]) if body is not None and body.mesh is not None else None
        if points is None or len(points) < 2:
            self.toast('Kliknij krawędź bryły albo linię, okrąg lub łuk szkicu.')
            return
        pts = np.asarray(points, float)
        length = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
        mesh = self._polyline_mesh(pts)
        radius = center = None
        try:
            edge = body.shape.Edges()[hit[1]]
            if edge.geomType() == 'CIRCLE':
                radius, length = float(edge.radius()), float(edge.Length())
                center = np.array(edge.arcCenter().toTuple(), float)
        except Exception:
            pass
        if radius is None:
            radius, center = _fit_circle(pts)
        if radius is None:
            self._measure_show(f'<b>Długość krawędzi: {length:.3f} mm</b><br>To nie jest okrąg ani łuk.', [mesh])
            return
        meshes = [mesh, *self._cross(center, max(radius * .1, .5)), self._polyline_mesh([center, pts[0]])]
        self._measure_show(f'<b>Promień: {radius:.3f} mm</b><br>Średnica: {2 * radius:.3f} mm<br>Długość krawędzi: {length:.3f} mm<br>Środek: ({center[0]:.2f}; {center[1]:.2f}; {center[2]:.2f})', meshes)

    def _measure_props(self, x, y):
        hit = self.view.pick_face(x, y)
        edge = None if hit else self.view.nearest_edge(x, y)
        bid = hit[0] if hit else ((self.view.pick_body(x,y) if self.view.section_plane is not None else None) or self.view.pick_profile(x, y) or (edge[0] if edge else None))
        body = self.document.get(bid) if bid else None
        if body is None:
            self.toast('Kliknij bryłę albo zamknięty szkic.')
            return
        mesh = body.mesh
        if body.kind == 'solid':
            box = kernel.bounds(body.shape)
            c = _center(body.shape)
            vol = float(body.shape.Volume())
            self._measure_show(f'<b>{body.name}</b><br>Objętość: {vol:,.2f} mm³ ({vol / 1000:,.3f} cm³)<br>Pole powierzchni: {float(body.shape.Area()):,.2f} mm²<br>'
                               f'Wymiary: {box.xmax - box.xmin:.3f} × {box.ymax - box.ymin:.3f} × {box.zmax - box.zmin:.3f} mm<br>Środek masy: ({c.x:.2f}; {c.y:.2f}; {c.z:.2f})',
                               [mesh] if mesh is not None else None)
            return
        face = profile_face(body.shape)
        perimeter = float(sum(e.Length() for e in body.shape.Edges()))
        area = f'Pole: {float(face.Area()):,.3f} mm²<br>' if face is not None and body.shape.IsClosed() else 'Szkic otwarty - brak pola.<br>'
        self._measure_show(f'<b>{body.name}</b><br>{area}Obwód / długość: {perimeter:,.3f} mm', [mesh] if mesh is not None else None)

    # =====================================================================
    # rysunek techniczny
    # =====================================================================
    def pick_drawing(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij bryłę (nie szkic).')
            return
        mode = self.mode
        if mode == 'plydrawing':
            from . import plywood as pw
            if not pw.is_panel(body):
                self.toast('Kliknij płytę ze sklejki (z zakładki Sklejka).')
                return
            self.set_mode(None)
            self.open_ply_drawing(body)
            return
        if mode == 'sheetdrawing':
            if self._editable_sheet_state(body.id) is None:
                self.toast('Kliknij blachę (bryłę zamienioną na blachę, z zapisanymi gięciami).')
                return
            self.set_mode(None)
            self.open_sheet_drawing(body)
            return
        self.set_mode(None)
        self.open_drawing(body, auto=mode == 'autodrawing')

    def open_sheet_drawing(self, body):
        """Rysunek blachy do gięcia: rozwinięcie (liczone w tle także z blachy zgiętej) z liniami gięcia, łańcuchami wymiarów
        od krawędzi i między liniami, opisem gięć (kierunek, kąt, promień) oraz grubością - w oknie rysunku do sprawdzenia i zapisu."""
        from .drawing_window import DrawingWindow
        state = self._editable_sheet_state(body.id)
        if state is None:
            self.toast('To nie jest blacha z zapisanymi gięciami.')
            return
        source=body if (body.meta or {}).get('sheet') else replace(body,meta=dict(body.meta or {},sheet=state))
        existing=[source if b.id==body.id else b for b in self.document.bodies]
        def build():
            bodies=hist.ensure_sheet_joints(existing,body.id)
            target=next(b for b in bodies if b.id==body.id)
            shape=target.shape;state=target.meta['sheet']
            moves=None if state.get('flat') else hist.sheet_tab_matrices(bodies,target,target,True)
            flat_walls, folded_walls = self._flat_tab_walls(target,bodies,moves), self._folded_tab_walls(target,bodies)
            flat = shape if state.get('flat') else she.switch(shape, state, True)[0]
            flat_state = dict(state, flat=True)
            lines = [*she.flat_bend_lines(flat, flat_state),*self._tab_bend_lines(target,bodies,moves)]
            k = float((state['recipe'].get('rules') or {}).get('kfactor', shm.K_DEFAULT))
            bends = [(l['a'], l['b'], l['direction'], dict(angle=l.get('angle'), r=l.get('r'), index=l.get('index'))) for l in lines]
            folded = self._folded_of(shape, state)
            if flat_walls:
                flat = kernel.compound([flat, *flat_walls])
            if folded is not None and folded_walls:
                folded = kernel.compound([folded, *folded_walls])
            return flat, bends, dict(t=float(state['recipe']['t']), k=k), folded

        def apply(result):
            flat, bends, sheet, folded = result
            win = DrawingWindow(flat, f'{body.name} — rozwinięcie', self, views=('top', 'iso') if folded is not None else ('top',),
                                checked=('top',), bends=bends, sheet=sheet, iso_shape=folded)
            self._drawing_windows = [w for w in self._drawing_windows if w.isVisible()] + [win]
            win.show()
            win.raise_()

        self.run_operation('Rysunek blachy', build, apply)

    def open_ply_drawing(self, body):
        """Rysunek płyt: wszystkie płyty z grupy klikniętej płyty (bez grupy - wszystkie widoczne płyty) rozłożone płasko,
        każda z nazwą i wymiarami; widok izometryczny pokazuje całość złożoną."""
        from . import plywood as pw
        from .drawing_window import DrawingWindow
        chosen = [b for b in self.document.bodies if pw.is_panel(b) and b.visible and (b.folder == body.folder if body.folder else True)]
        items = [(b.name, b.shape, b.meta['ply'].get('t')) for b in chosen]
        name = body.folder or 'Płyty'

        def build():
            flat, parts = pw.drawing_parts(items)
            whole = kernel.compound([s for _, s, _ in items]) if len(items) > 1 else items[0][1]
            return flat, parts, whole

        def apply(result):
            flat, parts, whole = result
            win = DrawingWindow(flat, f'{name} — płyty', self, views=('top', 'iso'), checked=('top',), iso_shape=whole, parts=parts)
            self._drawing_windows = [w for w in self._drawing_windows if w.isVisible()] + [win]
            win.show()
            win.raise_()

        self.run_operation('Rysunek płyt', build, apply)

    def _flat_sheet_bends(self, body):
        """Funkcja licząca linie gięcia rozłożonej blachy (w górę / w dół, przycięte do obrysu) albo None, gdy bryła nie jest płaską blachą."""
        meta = (body.meta or {}).get('sheet') if body is not None else None
        if not meta or not meta.get('flat'):
            return None
        state = self._editable_sheet_state(body.id)
        if state is None:
            return None
        shape = body.shape

        def compute():
            """(linie gięcia, blacha zgięta do widoku izometrycznego albo None)."""
            try:
                bends = [(l['a'], l['b'], l['direction'], dict(angle=l.get('angle'), r=l.get('r'), index=l.get('index'))) for l in she.flat_bend_lines(shape, state)]
            except Exception:
                bends = []          # rysunek powstaje także wtedy, gdy linii gięcia nie da się wyznaczyć
            return bends, self._folded_of(shape, state)
        return compute

    @staticmethod
    def _folded_of(shape, state):
        """Zgięta postać blachy (do widoku izometrycznego rysunku); None, gdy nie da się jej wyznaczyć."""
        try:
            return shape if not state.get('flat') else she.switch(shape, state, False)[0]
        except Exception:
            return None

    def open_drawing(self, body, auto=False):
        from . import drawing as dr
        from .drawing_window import DrawingWindow, FILTERS, export_drawing
        bends_of = self._flat_sheet_bends(body)
        if not auto:
            def show(result):
                bends, folded = result if result is not None else (None, None)
                win = DrawingWindow(body.shape, body.name, self, bends=bends, iso_shape=folded)
                self._drawing_windows = [w for w in self._drawing_windows if w.isVisible()] + [win]
                win.show()
                win.raise_()
            if bends_of is None:
                show(None)
            else:       # rozłożona blacha: linie gięcia liczone w tle, potem okno rysunku
                self.run_operation('Linie gięcia', bends_of, show)
            return

        def build():
            from . import FULL_VERSION
            bends, folded = bends_of() if bends_of else (None, None)
            source = dr.DrawingSource(body.shape, body.name, bends, iso_shape=folded)
            return dr.build_drawing(source, version=FULL_VERSION, **dr.auto_settings(source))

        def apply(drawing):
            path, _ = QFileDialog.getSaveFileName(self, 'Zapisz rysunek techniczny', f'{body.name}.pdf', FILTERS)
            if not path:
                return
            if not Path(path).suffix:
                path += '.pdf'
            export_drawing(drawing, path)
            self.toast('Zapisano rysunek: ' + path, 6000)

        self.run_operation('Rysunek automatyczny', build, apply)

    def import_drawing_file(self, path=None):
        """Zakładka Rysunek → Załaduj plik: płaski rysunek SVG albo DXF z dysku otwierany w oknie rysunku technicznego (rzut z góry)."""
        if self.busy:
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, 'Załaduj plik do rysunku technicznego', '', 'Rysunki 2D (*.svg *.dxf);;SVG (*.svg);;DXF (*.dxf)')
        if not path:
            return
        from . import import2d
        name = Path(path).stem

        def apply(parts):
            from .drawing_window import DrawingWindow
            shape, bends = parts
            self.set_mode(None)
            win = DrawingWindow(shape, name, self, views=('top',), bends=bends)
            self._drawing_windows = [w for w in self._drawing_windows if w.isVisible()] + [win]
            win.show()
            win.raise_()

        self.run_operation('Wczytywanie rysunku', lambda: import2d.load_flat_parts(path), apply)

    # =====================================================================
    # skorupa
    # =====================================================================
    def pick_sheet(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij bryłę (nie szkic).')
            return
        try:
            face, normal = self.view.face_at(body,hit)
            info = shm.sheet_of_face(body.shape, face)
        except kernel.CadError as exc:
            self.sheet_pick = None
            self.view.set_selection_meshes(None)
            self.sheet_t.setText('—')
            self.sheet_dims.setText('—')
            self.sheet_status.setText(str(exc))
            return
        self.sheet_pick = dict(id=body.id, face=face, normal=tuple(float(c) for c in normal), point=tuple(float(c) for c in hit[2]), info=info)
        self.view.set_selection_meshes([kernel.display_mesh(face)], color=(1, .55, .1, .55), line_color=SKETCH_ORANGE)
        a, b = info['dims']
        num = lambda v: f'{v:.2f}'.rstrip('0').rstrip('.').replace('.', ',')
        self.sheet_t.setText(f'{num(info["t"])} mm')
        self.sheet_dims.setText(f'{num(max(a, b))} × {num(min(a, b))} mm')
        self.sheet_status.setText('Kliknij „Zamień na blachę”.')

    def apply_sheet(self):
        pick = self.sheet_pick
        body = self.document.get(pick['id']) if pick else None
        if self.busy or body is None:
            self.toast('Kliknij płaską ścianę prostopadłościanu.')
            return
        info = pick['info']
        recipe = dict(type='sheet', id=body.id, face=hist.face_ref(pick['face'], pick['normal'], pick['point'], body.shape),
                      base=info['base'], t=info['t'], rules=self._flange_rules())
        self.sheet_pick = None
        self.view.set_selection_meshes(None)
        metadata=she.state(dict(base=info['base'],t=info['t'],flanges=[],rules=recipe['rules']))
        self.document.commit([replace(b,meta={'sheet':metadata}) if b.id==body.id else b for b in self.document.bodies], label='Konwersja na blachę', icon='sheet', op=recipe)
        self._tool_select([body.id])
        self.set_mode(None)

    def _flange_rules(self):
        return dict(gap=float(self.fl_gap.value()), relief=self.fl_relief.currentData() or 'none',
                    relief_size=float(self.fl_relief_size.value()), miter=True, auto_corners=True, joint=self.fl_joint.currentData() or 'parallel',
                    outside=self.fl_outside.isChecked(), kfactor=float(self.fl_kfactor.value()))

    def _sheet_state(self, body_id):
        """Stan blachy odczytany z historii (do bieżącego kroku): płyta bazowa, grubość, lista kołnierzy i reguły.
        Nowe blachy zachowują opis gięć także po zwykłej edycji bryły.
        Dla starszych projektów opis jest odtwarzany z historii."""
        body=self.document.get(body_id)
        metadata=(body.meta or {}).get('sheet') if body else None
        if metadata:
            nominal=metadata['recipe']
            return dict(base=nominal['base'],t=nominal['t'],specs=list(nominal.get('flanges') or []),
                        rules=dict(nominal.get('rules') or {}),flat=metadata.get('flat',False),
                        dirty=metadata.get('dirty',False),edited=metadata.get('edited',False),bend_engine=metadata.get('bend_engine',1),joints=metadata.get('joints'))
        infos, cur = self.document.infos()
        state = None
        for info in infos[:cur + 1]:
            op = (info or {}).get('op') or {}
            kind = op.get('type')
            if kind == 'sheet' and op.get('id') == body_id and op.get('base') is not None:
                state = dict(base=op['base'], t=float(op['t']), specs=[], rules=dict(op.get('rules') or {}))
            elif kind == 'sheetbuild' and op.get('id') == body_id and state is not None:
                state = dict(base=state['base'], t=state['t'], specs=list(op['flanges']), rules=dict(op.get('rules') or {}))
            elif kind in ('extrude','revolve','sweep','loft') and op.get('mode')!='new' and state is not None:
                state['dirty']=True
            elif kind in ('mod','shell','bool') and body_id in {op.get('id'),op.get('base')} and state is not None:
                state['dirty']=True
            elif kind in ('transform','mirror','pattern','split') and body_id in {op.get('id'),op.get('base')} :
                state=None
        return state

    def _editable_sheet_state(self, body_id):
        source=self._sheet_state(body_id)
        if source is None:
            return None
        metadata=she.state(dict(base=source['base'],t=source['t'],flanges=source['specs'],rules=source['rules']),source.get('flat',False))
        metadata.update(dirty=source.get('dirty',False),edited=source.get('edited',False),bend_engine=source.get('bend_engine',1),joints=source.get('joints'))
        return metadata

    SHEET_COMMANDS = {'unfold_sheet': 'Rozłóż blachę', 'fold_sheet': 'Zegnij blachę', 'flat': 'Rozwinięcie DXF'}

    def _selected_sheet(self):
        chosen = [b for b in self.document.bodies if b.id in self.selected and b.kind == 'solid']
        roots = {self._tab_root(b).id: self._tab_root(b) for b in chosen}       # ścianka na noski -> jej blacha
        if len(roots) == 1:
            chosen = [*roots.values(), *[b for b in chosen if b.id not in roots]]
        tab = lambda b: (((b.meta or {}).get('ply') or {}).get('tab'))
        sheets = [b for b in chosen if not tab(b) and ((b.meta or {}).get('sheet') or (len(chosen) == 1 and self._sheet_state(b.id) is not None))]
        # blacha zaznaczona razem ze swoimi ściankami na noski (jedna grupa) - to nadal jedna blacha
        if len(sheets) == 1 and all(b is sheets[0] or ((b.meta or {}).get('ply') or {}).get('tab') for b in chosen):
            return sheets[0]
        return None

    def sheet_command(self, command):
        """Rozłóż / Zegnij: od razu na zaznaczonej blasze, a bez zaznaczenia - po wskazaniu jej kliknięciem.
        Rozwinięcie DXF: zawsze najpierw wskazanie blachy do zapisania."""
        if self.busy:
            return
        if self.mode == 'sheetpick' and self._sheet_cmd == command:
            self.set_mode(None)          # ponowne kliknięcie narzędzia anuluje wskazywanie
            return
        body = None if command == 'flat' else self._selected_sheet()
        if body is not None:
            self.tools[command].setChecked(False)
            self.switch_sheet(command, body)
            return
        self.set_mode('sheetpick')
        self._sheet_cmd = command
        self.tools[command].setChecked(True)
        self.view.setCursor(Qt.PointingHandCursor)
        what = {'unfold_sheet': 'rozłożyć', 'fold_sheet': 'zgiąć', 'flat': 'zapisać jako rozwinięcie DXF'}[command]
        self.hint(f'{self.SHEET_COMMANDS[command]}: kliknij blachę, którą chcesz {what}. Esc anuluje.')
        self.toast(f'Kliknij blachę, którą chcesz {what}.', 3000)

    def _tab_root(self, body):
        """Ścianka na noski -> blacha, na której stoi (przez kolejne ścianki); inne bryły bez zmian."""
        seen = set()
        while body is not None and ((body.meta or {}).get('ply') or {}).get('tab') and body.id not in seen:
            seen.add(body.id)
            parent = self.document.get(body.meta['ply']['tab'].get('sheet'))
            if parent is None:
                break
            body = parent
        return body

    def pick_sheet_command(self, x, y):
        bid = self.view.pick_body(x, y)
        body = self._tab_root(self.document.get(bid)) if bid else None
        if body is None or body.kind != 'solid' or self._sheet_state(body.id) is None:
            self.toast('To nie jest blacha. Kliknij blachę (najpierw KONWERTUJ NA BLACHĘ).')
            return
        command = self._sheet_cmd
        self.set_mode(None)
        self.tools[command].setChecked(False)
        self.selected = [body.id]
        self.refresh()
        if command == 'flat':
            self.export_flat_pattern(body)
        else:
            self.switch_sheet(command, body)

    def switch_sheet(self, command, body=None):
        if self.busy:
            return
        if body is None:
            body=self._selected_sheet()
        metadata=self._editable_sheet_state(body.id) if body else None
        if metadata is None:
            self.toast('Zaznacz jedną blachę z zapisaną historią gięć.')
            return
        sync=command=='sheet_sync'
        flat=metadata['flat'] if sync else command=='unfold_sheet'
        if not sync and flat==metadata['flat']:
            self.toast('Blacha jest już rozłożona.' if flat else 'Blacha jest już zgięta.')
            return
        label={'unfold_sheet':'Rozłóż blachę','fold_sheet':'Zegnij blachę','sheet_sync':'Aktualizuj blachę'}[command]
        recipe=dict(type='sheetmode',id=body.id,state=metadata,flat=flat,sync=sync)
        walls=hist.sheet_tab_walls(self.document.bodies, body.id)     # ścianki na noski rozkładają się / składają z blachą
        def build():
            return {b.id: b for b in hist.run_sheetmode([body, *walls],recipe)}
        def apply(result):
            self.document.commit([result.get(b.id, b) for b in self.document.bodies],label=label,icon=command,op=recipe)
            self._tool_select([body.id, *[w.id for w in walls]])
        self.set_mode(None)
        def shown():
            if not sync:
                name='XY' if flat else 'iso'
                self.view.set_view(name);self._mark_view(name);self.view.fit_all()
        self.run_operation(label,build,apply,fit=not sync,after=shown)

    def _edge_status(self):
        """Etykieta stanu wyboru krawędzi: osobna dla kołnierza i dla zawinięcia."""
        return self.hm_status if self.mode == 'hem' else self.fl_status

    def apply_sheet_rules(self):
        """Rebuild existing corners without adding an artificial extra flange."""
        if self.busy:
            return
        bodies = [b for b in self.document.bodies if b.id in self.selected and b.kind == 'solid']
        body = bodies[0] if len(bodies) == 1 else None
        state = self._sheet_state(body.id) if body else None
        if state is None:
            if self.mode == 'rules':
                self.rl_pick = True          # nic nie zaznaczono: wskaż blachę kliknięciem
                self.view.setCursor(Qt.PointingHandCursor)
                self.rl_status.setText('Kliknij blachę, do której zastosować reguły.')
                self.hint('Reguły blach: kliknij blachę.')
            else:
                self.toast('Zaznacz jedną blachę w drzewie obiektów, aby zastosować reguły narożników.')
            return
        self.rl_pick = False
        self.view.setCursor(Qt.ArrowCursor)
        specs = [dict(spec, outside=spec.get('outside', state['rules'].get('outside',False))) for spec in state['specs']]
        recipe = dict(type='sheetbuild',id=body.id,base=state['base'],t=state['t'],flanges=specs,rules=self._flange_rules())
        def apply(result):
            self.document.commit([result.get(b.id,b) for b in self.document.bodies],
                                 label='Narożniki blachy',icon='flange',op=recipe)
            self._tool_select([body.id])
            if self.mode == 'rules':
                self.rl_status.setText(f'Reguły zastosowane do: {body.name}.')
        source=replace(body,meta=dict(body.meta or {},sheet=self._editable_sheet_state(body.id)))
        root=self._tab_root(body)
        member_ids={root.id,*[b.id for b in hist.sheet_tab_walls(self.document.bodies,root.id)]}
        members=[source if b.id==body.id else b for b in self.document.bodies if b.id in member_ids]
        self.run_operation('Narożniki blachy',lambda:{b.id:b for b in hist.run_sheetbuild(members,recipe)},apply)

    def pick_rules_sheet(self, x, y):
        bid = self.view.pick_body(x, y)
        body = self.document.get(bid) if bid else None
        if body is None or body.kind != 'solid' or self._sheet_state(body.id) is None:
            self.rl_status.setText('To nie jest blacha. Kliknij blachę (najpierw KONWERTUJ NA BLACHĘ).')
            return
        self._tool_select([body.id])
        self.refresh()
        self.apply_sheet_rules()

    def confirm_sheet_rules(self):
        """Zastosuj: ustawienia zostają w polach (używa ich każde następne gięcie) i włącza się Kołnierz z wyginaniem."""
        if self.busy:
            return
        self.set_mode('flange')
        self.fl_armed = True
        self._style_bend_button()
        self.fl_status.setText('Wyginanie włączone: kliknij krawędź blachy.')
        self.toast('Reguły blach zatwierdzone - kliknij krawędź, aby dodać gięcie.', 3000)

    def reset_sheet_rules(self):
        """Reset: domyślne ustawienia reguł blach."""
        self.fl_gap.setValue(RULES_DEFAULT['gap'])
        self.fl_relief.setCurrentIndex(self.fl_relief.findData(RULES_DEFAULT['relief']))
        self.fl_relief_size.setValue(RULES_DEFAULT['relief_size'])
        self.fl_kfactor.setValue(shm.K_DEFAULT)
        self.fl_joint.setCurrentIndex(self.fl_joint.findData(RULES_DEFAULT['joint']))
        self.fl_outside.setChecked(False)
        self.rl_status.setText('Przywrócono ustawienia domyślne.')

    def pick_flange(self, x, y):
        hit = self.view.nearest_edge(x, y, True)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij krawędź bryły blachy.')
            return
        st = self._sheet_state(body.id)
        if st is None:
            self.fl_pick = None
            self.view.set_picked_edge(None)
            self._edge_status().setText('To nie jest blacha (albo zmieniła się po konwersji). Kliknij KONWERTUJ NA BLACHĘ.')
            return
        if st.get('flat') or (((body.meta or {}).get('ply') or {}).get('tab') or {}).get('unfold'):
            self.toast('Najpierw zegnij blachę, zanim dodasz kolejne gięcie.')
            return
        self.fl_joint.setCurrentIndex(self.fl_joint.findData(('sheet' if st['rules'].get('joint') == 'diagonal' else st['rules'].get('joint','parallel'))))
        box = body.shape.BoundingBox()
        tol = max(1e-3, 0.001 * max(box.xlen, box.ylen, box.zlen))
        mid = body.shape.Edges()[hit[1]].positionAt(.5).toTuple()
        try:
            spec = shm.spec_for_edge(st['base'], st['t'], st['specs'], st['rules'], mid, tol)
        except kernel.CadError as exc:
            self.fl_pick = None
            self.view.set_picked_edge(None)
            self._edge_status().setText(str(exc))
            return
        self.fl_pick = dict(id=body.id, spec=spec)
        self.view.set_picked_edge(hit)
        if getattr(self, 'fl_armed', False):
            self._add_pick()
            return
        more = ' Kliknij Zaginaj (zielony), aby wyginać.'
        if spec['kind'] == 'tip':
            self._edge_status().setText('Krawędź końca kołnierza: nowy kołnierz wychodzi z tego końca.' + more)
        else:
            up = float(spec['n'][2])
            self._edge_status().setText(('Krawędź górnej ściany: kołnierz w górę.' if up > .5 else 'Krawędź dolnej ściany: kołnierz w dół.' if up < -.5 else 'Kołnierz na zewnątrz tej ściany.') + more)

    def apply_flange(self):
        """Zatwierdź: zapisuje ustawienia kołnierza i dodaje wcześniej wskazaną krawędź. Potem klikanie krawędzi dodaje kolejne."""
        self._arm()

    def apply_hem(self):
        """Zatwierdź: zapisuje ustawienia zawinięcia i dodaje wcześniej wskazaną krawędź. Potem klikanie krawędzi dodaje kolejne."""
        self._arm()

    # ---------- Kołnierz: Zatwierdź / Zaginaj / Reset ----------
    @staticmethod
    def _settings_file(name='flange'):
        """Plik ustawienia w folderze „Ustawienia” obok programu (do przeniesienia przy aktualizacji)."""
        from . import settings
        return settings.path(name)

    def _read_settings(self, name):
        from . import settings
        return settings.read(name)

    def _write_settings(self, name, values):
        from . import settings
        return settings.write(name, values)

    # ---------- Zawinięcie: Zatwierdź / Reset ----------
    def _hem_values(self):
        return dict(radius=float(self.hm_radius.value()), length=float(self.hm_length.value()), gap=float(self.hm_gap.value()))

    def _set_hem_values(self, values):
        for key, spin in (('radius', self.hm_radius), ('length', self.hm_length), ('gap', self.hm_gap)):
            spin.setValue(float(values.get(key, HEM_DEFAULT[key])))

    def _load_hem_settings(self):
        values = self._read_settings('hem')
        if values:
            self._set_hem_values(values)

    def save_hem_settings(self):
        """Zatwierdź: utrwala ustawienia zawinięcia (także po ponownym uruchomieniu programu)."""
        values = self._hem_values()
        if not self._write_settings('hem', values):
            self.hm_status.setText('Nie udało się zapisać ustawień na dysku - obowiązują do zamknięcia programu.')
            return
        nums = [f'{values[k]:g}'.replace('.', ',') for k in ('radius', 'length', 'gap')]
        self.hm_status.setText(f'Zapamiętano: R {nums[0]} mm · długość do {nums[1]} mm · szczelina {nums[2]} mm.')

    def reset_hem_settings(self):
        """Reset: ustawienia domyślne zawinięcia (zapamiętane zostają dopiero po Zatwierdź)."""
        self._set_hem_values(HEM_DEFAULT)
        self.hm_status.setText('Przywrócono ustawienia domyślne. Zatwierdź, aby je zapamiętać.')

    def _flange_values(self):
        return dict(radius=float(self.fl_radius.value()), angle=float(self.fl_angle.value()), length=float(self.fl_length.value()),
                    measure=self.fl_datum.currentData())

    def _set_flange_values(self, values):
        self.fl_radius.setValue(float(values.get('radius', FLANGE_DEFAULT['radius'])))
        self.fl_angle.setValue(float(values.get('angle', FLANGE_DEFAULT['angle'])))
        self.fl_length.setValue(float(values.get('length', FLANGE_DEFAULT['length'])))
        index = self.fl_datum.findData(values.get('measure', FLANGE_DEFAULT['measure']))
        self.fl_datum.setCurrentIndex(index if index >= 0 else 0)

    def _load_flange_settings(self):
        values = self._read_settings('flange')
        if values:
            self._set_flange_values(values)

    def save_flange_settings(self):
        """Zatwierdź: utrwala ustawienia kołnierza (także po ponownym uruchomieniu programu)."""
        values = self._flange_values()
        if not self._write_settings('flange', values):
            self.fl_status.setText('Nie udało się zapisać ustawień na dysku - obowiązują do zamknięcia programu.')
            return
        side = 'zewnętrznej' if values['measure'] == 'outer' else 'wewnętrznej'
        nums = [f'{values[k]:g}'.replace('.', ',') for k in ('radius', 'angle', 'length')]
        self.fl_status.setText(f'Zapamiętano: R {nums[0]} mm · {nums[1]}° · {nums[2]} mm od strony {side}.')

    def reset_flange_settings(self):
        """Reset: ustawienia domyślne kołnierza (zapamiętane zostają dopiero po Zatwierdź)."""
        self._set_flange_values(FLANGE_DEFAULT)
        self.fl_reverse.setChecked(False)
        self.fl_status.setText('Przywrócono ustawienia domyślne. Zatwierdź, aby je zapamiętać.')

    def toggle_bending(self):
        """Zaginaj: czerwony = kliknięcie krawędzi dodaje kołnierz, zielony = wyginanie wyłączone."""
        self.fl_armed = not self.fl_armed
        self.fl_pick = None
        self.view.set_picked_edge(None)
        self._style_bend_button()
        self._edge_status().setText('Wyginanie włączone: kliknij krawędź blachy.' if self.fl_armed else 'Wyginanie wyłączone. Kliknij Zaginaj, aby znów wyginać.')

    def _style_bend_button(self):
        on = bool(getattr(self, 'fl_armed', False))
        color, hover = ('#e5484d', '#cf3a3f') if on else ('#2fa56d', '#26905e')
        for button in (getattr(self, 'fl_bend', None), getattr(self, 'hm_bend', None)):
            if button is None:
                continue
            button.setStyleSheet(f'QPushButton{{background:{color};color:white;border:none;border-radius:8px;font-weight:700;padding:7px 10px;}}'
                                 f'QPushButton:hover{{background:{hover};}}')
            button.setProperty('armed', on)

    def cancel_edge(self):
        """Anuluj: wyłącza dodawanie kliknięciem i czyści wskazanie. Okno zostaje otwarte."""
        self.fl_armed = False
        self._style_bend_button()
        self.fl_pick = None
        self.view.set_picked_edge(None)
        self._edge_status().setText('Anulowano. Zatwierdź ustawienia, aby znów dodawać krawędzie kliknięciem.')

    def _arm(self):
        self.fl_armed = True
        self._style_bend_button()
        if self.fl_pick:
            self._add_pick()
        else:
            self._edge_status().setText('Ustawienia zatwierdzone. Kliknij krawędź blachy, aby ją dodać.')

    def _spec_now(self):
        """Specyfikacja kołnierza albo zawinięcia dla wskazanej krawędzi, z bieżących pól panelu."""
        spec = dict(self.fl_pick['spec'])
        if self.mode == 'hem':
            spec.update(r=float(self.hm_radius.value()), angle=90.0, length=float(self.hm_length.value()),
                        hem=dict(gap=float(self.hm_gap.value()), ret=float(self.hm_length.value())))
        else:
            spec.update(r=float(self.fl_radius.value()), angle=float(self.fl_angle.value()), length=float(self.fl_length.value()),
                        measure=self.fl_datum.currentData(), outside=False)
            if self.fl_reverse.isChecked():
                if spec['kind'] == 'tip':
                    spec['side'] = 'out' if spec['side'] == 'in' else 'in'
                else:
                    state = self._sheet_state(self.fl_pick['id'])
                    n = np.asarray(spec['n'], float)
                    spec['p0'] = (np.asarray(spec['p0']) - state['t'] * n).tolist()
                    spec['p1'] = (np.asarray(spec['p1']) - state['t'] * n).tolist()
                    spec['n'] = (-n).tolist()
        return spec

    def _add_pick(self):
        spec = self._spec_now()
        self._commit_edge(spec, 'Zawinięcie' if self.mode == 'hem' else 'Kołnierz')

    def _after_commit(self):
        self._edge_status().setText('Dodano. Kliknij kolejną krawędź; Zaginaj wyłącza wyginanie.')

    def _commit_edge(self, spec, label):
        pick = self.fl_pick
        body = self.document.get(pick['id']) if pick else None
        st = self._sheet_state(pick['id']) if pick else None
        if self.busy or body is None or st is None or spec is None:
            self.toast('Najpierw wybierz krawędź blachy.')
            return
        previous = [dict(s, outside=s.get('outside', st['rules'].get('outside', False))) for s in st['specs']]
        recipe = dict(type='sheetbuild', id=body.id, base=st['base'], t=st['t'], flanges=[*previous, spec], rules=self._flange_rules())

        source=replace(body,meta=dict(body.meta or {},sheet=dict(self._editable_sheet_state(body.id), **{k: v for k, v in ((body.meta or {}).get('sheet') or {}).items() if k == 'tabs'})))
        root=self._tab_root(body)
        member_ids={root.id,*[b.id for b in hist.sheet_tab_walls(self.document.bodies,root.id)]}
        members=[source if b.id==body.id else b for b in self.document.bodies if b.id in member_ids]
        def build():
            return {b.id: b for b in hist.run_sheetbuild(members,recipe)},recipe

        def apply(result):
            new, rec = result
            self.document.commit([new.get(b.id, b) for b in self.document.bodies], label=label, icon='flange', op=rec)
            self._tool_select([body.id])

        self.fl_pick = None
        self.view.set_picked_edge(None)
        self._quick_flange_preview(recipe)
        self.run_operation(label, build, apply, after=self._after_commit)

    def _quick_flange_preview(self, recipe):
        """Natychmiastowy podgląd nowego kołnierza / zawinięcia (sama jego bryła, bez narożników): widać go od razu po
        kliknięciu krawędzi, a dokładna blacha z narożnikami pojawia się po przeliczeniu w tle."""
        try:
            import cadquery as cq
            normal = shm.normalize(dict(base=recipe['base'], t=recipe['t'], flanges=recipe['flanges'], rules=recipe['rules']))
            eff, _ = shm._effective(normal['flanges'], float(normal['t']), True)
            pieces = shm._flange_parts(eff[-1], float(normal['t']))
            mesh = kernel.display_mesh(cq.Compound.makeCompound(pieces))
        except Exception:
            return
        self.view.set_preview_mesh(mesh, color=(.95, .6, .15, .55), line_color=SKETCH_ORANGE, width=2)
        self._quick_preview = True

    def export_flat_pattern(self, body=None):
        if self.busy:
            return
        if body is None:
            self.sheet_command('flat')       # najpierw wskazanie blachy do zapisania
            return
        state = self._sheet_state(body.id)
        if state is None:
            self.toast('Wybrana bryła nie ma aktualnej historii blachy.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Zapisz rozwinięcie 1:1 — mm', f'{body.name}-rozwiniecie.dxf', 'DXF (*.dxf)')
        if not path:
            return
        if not Path(path).suffix:
            path += '.dxf'
        def done(pattern):
            self.toast(f'Zapisano DXF 1:1 (mm): {path}. CUT: cięcie; BEND_UP/DOWN: linie gięcia, nie do cięcia. K={pattern["kfactor"]:.3f}.', 12000)

        metadata=self._editable_sheet_state(body.id)
        source=body if (body.meta or {}).get('sheet') else replace(body,meta=dict(body.meta or {},sheet=metadata))
        existing=[source if b.id==body.id else b for b in self.document.bodies]
        def build():
            bodies=hist.ensure_sheet_joints(existing,body.id)
            target=next(b for b in bodies if b.id==body.id)
            moves=None if target.meta['sheet'].get('flat') else hist.sheet_tab_matrices(bodies,target,target,True)
            extra=self._flat_tab_walls(target,bodies,moves)
            lines=self._tab_bend_lines(target,bodies,moves)
            return she.export_dxf(target.shape,target.meta['sheet'],path,extra,lines)
        self.run_operation('Rozwinięcie DXF',build,done)

    def _flat_tab_walls(self, body, bodies=None, moves=None):
        """Ścianki na noski blachy położone płasko obok jej rozwinięcia (do DXF i rysunku blachy)."""
        from . import plywood as pw
        bodies=self.document.bodies if bodies is None else bodies
        walls = hist.sheet_tab_walls(bodies, body.id)
        if not walls:
            return []
        state = (body.meta or {}).get('sheet') or {}
        if state.get('flat'):
            return [w.shape for w in walls]
        try:
            if moves is None:moves = hist.sheet_tab_matrices(bodies, body, body, True)
        except Exception as exc:
            raise kernel.CadError(f'Nie można rozwinąć wszystkich ścianek: {exc}. Eksport nie został wykonany.') from exc
        if len(moves)!=len(walls):
            raise kernel.CadError('Nie wszystkie ścianki mają położenie na rozwinięciu. Eksport nie został wykonany.')
        return [pw.apply_matrix(moves[w.id][1] if moves[w.id][1] is not None else w.shape, moves[w.id][0]) for w in walls if w.id in moves]

    def _tab_bend_lines(self,body,bodies=None,moves=None):
        """All wall bend lines in the same XY placement as their CUT contours."""
        from . import plywood as pw
        bodies=self.document.bodies if bodies is None else bodies
        walls=hist.sheet_tab_walls(bodies,body.id)
        flat=bool(body.meta['sheet'].get('flat'))
        moves={} if flat else moves if moves is not None else hist.sheet_tab_matrices(bodies,body,body,True)
        lines=[];offset=len(body.meta['sheet']['recipe']['flanges'])
        for wall in walls:
            st=wall.meta.get('sheet') or {}
            if not st.get('recipe',{}).get('flanges'):continue
            actual=wall.shape
            if flat:
                info=wall.meta['ply']['tab'].get('unfold')
                if not info:raise kernel.CadError(f'{wall.name}: brak położenia rozwinięcia.')
                M=pw._mat(info.get('acc'))@np.linalg.inv(pw._mat(info['M']))
                actual=pw.apply_matrix(actual,np.linalg.inv(M))
            else:
                M,local,developed=moves[wall.id]
                if local is None or developed is None:raise kernel.CadError(f'{wall.name}: brak rozwinięcia gięć ścianki.')
                actual,st=local,developed
            for line in she.flat_bend_lines(actual,st):
                value=dict(line,index=offset+line['index'])
                for key in ('a','b'):
                    point=line[key]
                    value[key]=(M@np.array([point[0],point[1],float(st['recipe']['t'])/2,1.]))[:2].tolist()
                if M[2,2]<0:value['direction']='DOWN' if value['direction']=='UP' else 'UP'
                value['thickness']=float(st['recipe']['t'])
                value['factor']=float(st['recipe'].get('rules',{}).get('kfactor',shm.K_DEFAULT))
                lines.append(value)
            offset+=len(st['recipe']['flanges'])
        return lines

    def _folded_tab_walls(self, body, bodies=None):
        bodies=self.document.bodies if bodies is None else bodies
        walls = hist.sheet_tab_walls(bodies, body.id)
        if not walls or not ((body.meta or {}).get('sheet') or {}).get('flat'):
            return [w.shape for w in walls]
        try:
            moves = hist.sheet_tab_matrices(bodies, body, body, False)
        except Exception as exc:
            raise kernel.CadError(f'Nie można złożyć wszystkich ścianek do rysunku: {exc}') from exc
        from . import plywood as pw
        return [moves[w.id][1] if moves[w.id][1] is not None else pw.apply_matrix(w.shape, moves[w.id][0]) for w in walls if w.id in moves]

    def pick_shell(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij bryłę (nie szkic).')
            return
        if body.id != self.sh_id:
            self.sh_id, self.sh_faces = body.id, []
            self._sh_update()
            return
        try:
            face, normal = self.view.face_at(body,hit)
        except kernel.CadError:
            self.toast('Otworzyć można tylko płaską ścianę.')
            return
        same = [f for f in self.sh_faces if f['face'].isSame(face)]
        if same:
            self.sh_faces = [f for f in self.sh_faces if f not in same]
        else:
            self.sh_faces.append(dict(face=face, normal=tuple(float(c) for c in normal), point=tuple(float(c) for c in hit[2])))
        self._sh_update()

    def _hover_shell_solid(self, x, y):
        """Przed wyborem bryła pod kursorem podświetla się na niebiesko - widać, którą skorupa obejmie."""
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid' or body.mesh is None:
            if self._hover_key is not None:
                self._hover_key = None
                self.view.set_preview_mesh(None)
            return
        key = ('shellsolid', body.id)
        if key != self._hover_key:
            self._hover_key = key
            self.view.set_preview_mesh(body.mesh, color=(.35, .65, .94, .45), line_color=(.1, .3, .6, 1), width=2)

    def _sh_xray(self, on):
        """W skorupie bryła jest przezroczysta, żeby wnętrze (a przy ściankach do wewnątrz także podgląd) było widać na żywo."""
        if on and getattr(self, '_sh_xray_prev', None) is None:
            self._sh_xray_prev = bool(self.view.xray)
            if not self.view.xray:
                self.view.set_xray(True)
        elif not on and getattr(self, '_sh_xray_prev', None) is not None:
            prev, self._sh_xray_prev = self._sh_xray_prev, None
            if bool(self.view.xray) != prev:
                self.view.set_xray(prev)

    def _sh_update(self):
        body = self.document.get(self.sh_id) if self.sh_id else None
        self._sh_xray(body is not None)
        if body is None or body.id not in self.selected or len(self.selected) < 2:     # kilka zaznaczonych - zostają zaznaczone
            self._tool_select([body.id] if body is not None else [])
        self._hover_key = None
        if body is None:
            self.sh_id, self.sh_faces = None, []
            self.sh_step1.set_state('active', 'Kliknij bryłę')
            self.sh_step2.set_state('pending', 'Najpierw wybierz bryłę')
            self.sh_status.setText('Kliknij bryłę, którą chcesz wydrążyć.')
            self.view.tints = {}
            self.view.set_selection_meshes(None)
            self.override = {}
            self.refresh()
            return
        many = len(self._multi_targets(body.id))
        self.sh_step1.set_state('done', body.name if many < 2 else f'{body.name} + {many - 1} zaznaczone (te same ustawienia)')
        self.sh_step2.set_state('done' if self.sh_faces else 'active', f'Otwarte ściany: {len(self.sh_faces)}' if self.sh_faces else 'Kliknij ściany (albo zatwierdź bez otwierania)')
        self.sh_status.setText('Kliknij ścianę, aby ją otworzyć; ponowne kliknięcie cofa. Enter zatwierdza.')
        meshes = []
        for f in self.sh_faces:
            try:
                meshes.append(kernel.display_mesh(f['face']))
            except Exception:
                pass
        self.view.set_selection_meshes(meshes or None, color=(.94, .6, .13, .55), line_color=(.8, .4, .05, 1))
        self.shell_panel.adjustSize()           # dłuższy opis nie może zasłonić przycisków kierunku
        self._place_shell_handle()
        self._timers['shell'].start()

    def _place_shell_handle(self):
        """Strzałka grubości ścianki na wydrążanej bryle: przeciąganie pogrubia / pocienia ścianki (podgląd na żywo)."""
        body = self.document.get(self.sh_id) if self.mode == 'shell' and self.sh_id else None
        if body is None:
            self.view.set_handles([])
            return
        b = kernel.bounds(body.shape)
        c = np.array(b.center.toTuple(), float)
        opened = [np.array(f['normal'], float) for f in self.sh_faces]
        sides = [((0, 0, 1), b.zmax - c[2]), ((1, 0, 0), b.xmax - c[0]), ((0, -1, 0), c[1] - b.ymin), ((-1, 0, 0), c[0] - b.xmin),
                 ((0, 1, 0), b.ymax - c[1]), ((0, 0, -1), c[2] - b.zmin)]
        n, reach = next(((np.array(v, float), r) for v, r in sides if not any(float(o @ np.array(v, float)) > .9 for o in opened)),
                        (np.array((0., 0., 1.)), b.zmax - c[2]))
        point = c + n * reach
        if self.sh_faces:
            last=self.sh_faces[-1];point=np.asarray(last['point'],float);n=np.asarray(last['normal'],float)
        inward = self.sh_dir.currentData() == 'in'
        d = -n if inward else n                         # strzałka w stronę, w którą rośnie ścianka
        t = float(self.sh_thick.value())
        base = point + d * t                            # podstawa strzałki na wewnętrznej / zewnętrznej powierzchni ścianki
        length = max(b.xlen, b.ylen, b.zlen) * .3
        self.view.set_handles([dict(id='shell', start=base, tip=base + d * length, dir=d, color=(.94, .6, .13, 1))])

    def update_shell_preview(self):
        body = self.document.get(self.sh_id) if self.mode == 'shell' and self.sh_id else None
        if body is None:
            return
        faces, thickness, inward = [f['face'] for f in self.sh_faces], self.sh_thick.value(), self.sh_dir.currentData() == 'in'

        def compute():
            return body.changed(*hist.offloaded_shape(hist.shell_indexed, body.shape, hist.face_indices(body.shape, faces), thickness, inward))

        def show(result, error):
            if self.mode != 'shell' or self.sh_id != body.id:
                return
            if error:
                self.override = {}
                self.sh_status.setText(error)
            else:
                self.override = {body.id: result}
            self.refresh()

        self.run_preview('shell', compute, show)

    def apply_shell(self):
        body = self.document.get(self.sh_id) if self.sh_id else None
        if self.busy or body is None:
            self.toast('Kliknij bryłę, którą chcesz wydrążyć.')
            return
        faces, thickness, inward = list(self.sh_faces), self.sh_thick.value(), self.sh_dir.currentData() == 'in'
        targets = self._multi_targets(body.id)
        if len(targets) > 1:          # kilka zaznaczonych: ta sama grubość; otwarte ściany o tym samym kierunku na każdej bryle
            steps = [dict(type='shell', id=body.id, faces=[hist.face_ref(f['face'], f['normal'], f['point'], body.shape) for f in faces],
                          thickness=thickness, inward=inward)]
            for i in targets[1:]:
                other = self.document.get(i)
                refs = []
                for f in faces:
                    match = hist.outer_face_along(other.shape, np.asarray(f['normal'], float))
                    if match is not None:
                        refs.append(hist.face_ref(match[0], match[1], np.array(match[0].Center().toTuple(), float), other.shape))
                steps.append(dict(type='shell', id=i, faces=refs, thickness=thickness, inward=inward))
            self.override = {}
            self.view.set_selection_meshes(None)
            self._run_multi('Skorupa', 'shell', steps, targets)
            return

        def build():
            new = body.changed(*hist.offloaded_shape(hist.shell_indexed, body.shape, hist.face_indices(body.shape, [f['face'] for f in faces]), thickness, inward))
            recipe = dict(type='shell', id=body.id, faces=[hist.face_ref(f['face'], f['normal'], f['point'], body.shape) for f in faces], thickness=thickness, inward=inward)
            return new, recipe

        def apply(result):
            new, recipe = result
            self.document.pending_op = recipe
            self.document.commit([new if b.id == body.id else b for b in self.document.bodies])
            self._tool_select([body.id])

        self.override = {}
        self.view.set_selection_meshes(None)
        self.run_operation('Skorupa', build, apply, after=lambda: self.set_mode(None))

    # =====================================================================
    # przeciągnięcie (profil wzdłuż ścieżki) i wyciągnięcie złożone (loft)
    # =====================================================================
    def _profile_group(self, x, y):
        try:
            src = self._profile_at(x, y)
        except Exception as exc:
            self.toast(str(exc) or 'Nie udało się wybrać profilu.')
            return None
        if src is not None and src.get('kind') == 'cyl':
            src = None      # ściana walcowa zmienia promień tylko w Wyciągnij
        if src is None:
            self.toast('Kliknij zamknięty profil szkicu albo płaską ścianę bryły.')
        return src

    @staticmethod
    def _same_profile(a, b):
        return a['kind'] == b['kind'] and a['id'] == b['id'] and np.allclose(a['center'], b['center'], atol=1e-6)

    def _profile_meshes(self, profiles):
        meshes = []
        for src in profiles:
            try:
                face = src.get('face') or profile_face(src['wire'])
                if face is not None:
                    meshes.append(kernel.display_mesh(face))
            except Exception:
                pass
        return meshes

    @staticmethod
    def _polyline_mesh(points):
        pts = np.asarray(points, np.float32)
        return kernel.DisplayMesh(np.zeros((0, 3), np.float32), np.zeros((0, 3), np.uint32), {0: pts}, tuple(float(c) for c in pts.mean(axis=0)), 1.0)

    def _merged_preview(self, makers, op):
        def compute():          # bryły podglądu liczy proces roboczy - okno w tym czasie działa normalnie
            return _merge_meshes(hist.background(hist.preview_meshes, makers, PREVIEW_TOL))

        def style(mesh):
            red = op == 'cut'
            color = (.9, .2, .2, .7) if red else ((.3, .75, .5, .72) if op == 'intersect' else PREVIEW_BLUE)
            self.view.set_preview_mesh(mesh, color=color, line_color=(.56, .07, .07, 1) if red else (.14, .3, .45, 1), width=2)

        return compute, style

    # ---------- przeciągnięcie ----------
    def pick_sweep(self, x, y, shift=False):
        if self.sw_profiles and self.sw_path is None:
            self._sw_pick_path(x, y)
            return
        src = self._profile_group(x, y)
        if src is None:
            return
        group = [src, *src.get('siblings', ())]
        if shift:
            if src.get('letters'):
                group = [src]
            dup = [p for p in self.sw_profiles if (p.get('cluster') is not None and p.get('cluster') == src.get('cluster') and not src.get('letters')) or self._same_profile(p, src)]
            self.sw_profiles = [p for p in self.sw_profiles if p not in dup] if dup else [*self.sw_profiles, *group]
        else:
            self.sw_profiles = group
        self._hover_key = None
        self.view.set_preview_mesh(None)
        self._sw_update()

    def _sw_pick_path(self, x, y):
        hit = self.view.nearest_edge(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None:
            self.toast('Kliknij linię lub łuk szkicu albo krawędź bryły jako ścieżkę.')
            return
        try:
            spec = dict(k='sketch', id=body.id) if body.kind == 'sketch' else dict(k='edge', id=body.id, ref=hist.edge_refs(body.shape, [hit[1]])[0])
            hist.resolve_path(self.document.bodies, spec)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        self.sw_path = spec
        self.view._set_hover_edge(None)
        self._sw_update()

    def _sw_reset_path(self):
        self.sw_path = None
        self._sw_update()

    def _sw_update(self):
        have, path = bool(self.sw_profiles), self.sw_path is not None
        self.sw_step1.set_state('done' if have else 'active', f'Wybrano: {len(self.sw_profiles)}' if have else 'Kliknij profil lub ścianę')
        self.sw_step2.set_state('done' if path else ('active' if have else 'pending'), 'Wskazana' if path else ('Kliknij linię, łuk lub krawędź' if have else 'Najpierw wybierz profil'))
        self.sw_again.setVisible(path)
        self.sw_status.setText('Kliknij zamknięty profil szkicu lub płaską ścianę bryły.' if not have else
                               ('Kliknij ścieżkę: linię lub łuk szkicu albo krawędź bryły.' if not path else 'Profil powinien leżeć na początku ścieżki. Enter zatwierdza.'))
        meshes = self._profile_meshes(self.sw_profiles)
        if path:
            try:
                meshes.append(kernel.display_mesh(hist.resolve_path(self.document.bodies, self.sw_path)))
            except Exception:
                pass
        self.view.set_selection_meshes(meshes or None)
        if not (have and path):
            self._result_preview = False
            self.view.set_preview_mesh(None)
            return
        self._timers['sweep'].start()

    def _sw_tools(self):
        if not self.sw_profiles or self.sw_path is None:
            raise kernel.CadError('Wybierz profil i ścieżkę.')
        path = hist.resolve_path(self.document.bodies, self.sw_path)
        return [partial(hist.sweep_profile, src, path) for src in self.sw_profiles]

    def update_sweep_preview(self):
        if self.mode != 'sweep' or not self.sw_profiles or self.sw_path is None:
            return
        try:
            makers = self._sw_tools()
        except kernel.CadError:
            return
        compute, style = self._merged_preview(makers, self.sw_op.currentData())

        def show(mesh, error):
            if self.mode != 'sweep' or not self.sw_profiles or self.sw_path is None:
                return
            if error:
                self._result_preview = False
                self.view.set_preview_mesh(None)
                self.sw_status.setText(error)
                return
            style(mesh)
            self._result_preview = True
            self.sw_status.setText('Profil powinien leżeć na początku ścieżki. Enter zatwierdza.')

        self.run_preview('sweep', compute, show)

    def apply_sweep(self):
        if self.busy or not self.sw_profiles or self.sw_path is None:
            self.toast('Wybierz profil i ścieżkę.')
            return
        try:
            makers = self._sw_tools()
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        op, path = self.sw_op.currentData(), dict(self.sw_path)
        existing, profiles = list(self.document.bodies), list(self.sw_profiles)
        spent = self._consumed_sketches(profiles)
        out = [uuid.uuid4().hex for _ in makers]

        skip = sorted(self._protected())
        folder = self._new_folder(profiles, spent, len(makers), op, 'Przeciągnięcie')

        def build():
            bodies = hist.offloaded(hist.combine, existing, [m() for m in makers], op, spent, out, 'Przeciągnięcie', skip=skip, folder=folder)
            recipe = dict(type='sweep', mode=op, path=path, profiles=hist.describe_profiles(profiles, existing), spent=sorted(spent), out=out)
            if skip:
                recipe['skip'] = skip
            if folder:
                recipe['folder'] = folder
            return bodies, recipe

        self._finish_solid_op({'new': 'Przeciągnięcie', 'join': 'Przeciągnięcie (dodaj)', 'cut': 'Przeciągnięcie (wytnij)', 'intersect': 'Przeciągnięcie (część wspólna)'}[op], build, op)

    def _finish_solid_op(self, label, build, op):
        def apply(result):
            bodies, recipe = result
            self.document.pending_op = recipe
            self.document.commit(bodies)
            self._tool_select([bodies[-1].id] if op == 'new' else [])

        self.view.set_preview_mesh(None)
        self.run_operation(label, build, apply, after=lambda: self.set_mode(None))

    # ---------- wyciągnięcie złożone ----------
    def pick_loft(self, x, y):
        if self.lf_kind.currentData() == 'point' and self.lf_profiles and self.lf_point is None:
            vertex = self.view.nearest_vertex(x, y, solids_only=False)
            if vertex is None:
                self.toast('Kliknij punkt szkicu albo narożnik bryły jako koniec.')
                return
            self.lf_point = tuple(float(c) for c in vertex[1])
            self.view.hover_vertex = None
            self._lf_update()
            return
        src = self._profile_group(x, y)
        if src is None:
            return
        same = [p for p in self.lf_profiles if self._same_profile(p, src)]
        self.lf_profiles = [p for p in self.lf_profiles if p not in same] if same else [*self.lf_profiles, src]
        if not self.lf_profiles:
            self.lf_point = None
        self._hover_key = None
        self.view.set_preview_mesh(None)
        self._lf_update()

    def _lf_drop_last(self):
        if self.lf_point is not None:
            self.lf_point = None
        elif self.lf_profiles:
            self.lf_profiles = self.lf_profiles[:-1]
        self._lf_update()

    def _lf_kind_changed(self):
        self.lf_point = None
        self._lf_update()

    def _lf_update(self):
        point_mode = self.lf_kind.currentData() == 'point'
        n = len(self.lf_profiles)
        self.lf_step1.set_state('done' if n >= (1 if point_mode else 2) else 'active', f'Wybrano: {n}' if n else 'Kliknij pierwszy profil')
        if not point_mode:
            self.lf_step2.set_state('pending', 'Nie dotyczy (wybierz „Do punktu”)')
        else:
            self.lf_step2.set_state('done' if self.lf_point is not None else ('active' if n else 'pending'), 'Wskazany' if self.lf_point is not None else ('Kliknij punkt lub narożnik' if n else 'Najpierw wybierz profil'))
        ready = self._lf_ready()
        order = ' → '.join(str(i + 1) for i in range(n)) + (' → punkt' if self.lf_point is not None else '')
        self.lf_status.setText(('Kolejność: ' + order + '. ' if n else '') + ('Enter zatwierdza.' if ready else ('Kliknij punkt końcowy.' if point_mode and n else 'Kliknij kolejne profile (ponowne kliknięcie usuwa profil).')))
        self.lf_last.setVisible(n > 0)
        meshes = self._profile_meshes(self.lf_profiles)
        if self.lf_point is not None:
            q, r = np.array(self.lf_point, float), 2.0
            for axis in np.eye(3):
                meshes.append(self._polyline_mesh([q - axis * r, q + axis * r]))
        self.view.set_selection_meshes(meshes or None)
        if not ready:
            self._result_preview = False
            self.view.set_preview_mesh(None)
            return
        self._timers['loft'].start()

    def _lf_ready(self):
        return len(self.lf_profiles) >= 2 or (self.lf_kind.currentData() == 'point' and bool(self.lf_profiles) and self.lf_point is not None)

    def _lf_tool(self):
        if not self._lf_ready():
            raise kernel.CadError('Wybierz co najmniej dwa profile albo profil i punkt.')
        wires = [hist.profile_outer(p).outerWire() for p in self.lf_profiles]
        point, ruled = self.lf_point if self.lf_kind.currentData() == 'point' else None, self.lf_ruled.currentData() == 'ruled'
        return partial(kernel.loft_wires, wires, point, ruled)

    def update_loft_preview(self):
        if self.mode != 'loft' or not self._lf_ready():
            return
        try:
            maker = self._lf_tool()
        except kernel.CadError:
            return
        compute, style = self._merged_preview([maker], self.lf_op.currentData())

        def show(mesh, error):
            if self.mode != 'loft' or not self._lf_ready():
                return
            if error:
                self._result_preview = False
                self.view.set_preview_mesh(None)
                self.lf_status.setText(error)
                return
            style(mesh)
            self._result_preview = True

        self.run_preview('loft', compute, show)

    def apply_loft(self):
        if self.busy or not self._lf_ready():
            self.toast('Wybierz co najmniej dwa profile albo profil i punkt.')
            return
        try:
            maker = self._lf_tool()
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        op, ruled = self.lf_op.currentData(), self.lf_ruled.currentData() == 'ruled'
        existing, profiles, point = list(self.document.bodies), list(self.lf_profiles), self.lf_point if self.lf_kind.currentData() == 'point' else None
        spent = self._consumed_sketches(profiles)
        out = [uuid.uuid4().hex]

        skip = sorted(self._protected())

        def build():
            bodies = hist.combine(existing, [maker()], op, spent, out, 'Wyciągnięcie złożone', skip=skip)
            specs = [hist.describe_profiles([p], existing, merge=False)[0] for p in profiles]
            recipe = dict(type='loft', mode=op, ruled=ruled, profiles=specs, spent=sorted(spent), out=out)
            if skip:
                recipe['skip'] = skip
            if point is not None:
                recipe['point'] = dict(p=[float(c) for c in point])
            return bodies, recipe

        self._finish_solid_op({'new': 'Wyciągnięcie złożone', 'join': 'Wyciągnięcie złożone (dodaj)', 'cut': 'Wyciągnięcie złożone (wytnij)',
                               'intersect': 'Wyciągnięcie złożone (część wspólna)'}[op], build, op)

    # =====================================================================
    # boolean
    # =====================================================================
    def pick_bool(self, x, y):
        bid = self.view.pick_body(x, y)
        body = self.document.get(bid) if bid else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij bryłę (nie szkic).')
            return
        if bid in self.bool_ids:
            self.bool_ids.remove(bid)
        else:
            self.bool_ids.append(bid)
        self.update_bool_status()

    def update_bool_status(self):
        self.view.tints = {bid: (TINT_BASE if i == 0 else TINT_TOOL) for i, bid in enumerate(self.bool_ids)}
        names = [self.document.get(i).name for i in self.bool_ids if self.document.get(i)]
        if not names:
            text = 'Kliknij bryłę bazową.'
        elif len(names) == 1:
            text = f'Baza: {names[0]}\nKliknij bryłę-narzędzie.'
        else:
            text = f'Baza: {names[0]}\nNarzędzia: {", ".join(names[1:])}'
        self.bool_status.setText(text)
        self.refresh()
        self._timers['bool'].start()

    def update_bool_preview(self):
        if self.mode != 'bool':
            return
        if len(self.bool_ids) < 2:
            self.cancel_previews()
            self.view.set_preview_mesh(None)
            return
        base, *tools = [self.document.get(i) for i in self.bool_ids]
        op = self.bool_op.currentData()
        ids = tuple(self.bool_ids)

        def compute():
            return hist.background(hist.mesh_of, kernel.boolean, (op, base.shape, [t.shape for t in tools]), PREVIEW_TOL)

        def show(mesh, error):
            if self.mode != 'bool' or tuple(self.bool_ids) != ids:
                return
            if error:
                self.view.set_preview_mesh(None)
                self.bool_status.setText(self.bool_status.text().split('\n\n')[0] + '\n\n' + error)
                return
            self.view.set_preview_mesh(mesh, color=(.3, .8, .5, .55), line_color=(.05, .4, .2, 1), width=2)

        self.run_preview('bool', compute, show)
    def apply_bool(self):
        if self.busy:
            return
        if len(self.bool_ids) < 2:
            self.toast('Do operacji Boolean potrzebne są co najmniej dwie bryły.')
            return
        bodies = [self.document.get(i) for i in self.bool_ids]
        base, tools = bodies[0], bodies[1:]
        ids = {b.id for b in tools}
        op = self.bool_op.currentData()
        keep = self.bool_keep.isChecked()

        recipe = dict(type='bool', op=op, base=base.id, tools=[b.id for b in tools], keep=keep)
        existing = list(self.document.bodies)

        def build():
            return list(hist.offloaded(hist.run_bool, existing, recipe))

        def apply(new):
            self.document.pending_op = recipe
            self.document.commit(new)
            self._tool_select([base.id])

        self.view.set_preview_mesh(None)
        def again():
            if self.mode=='bool':
                self.bool_ids=[base.id] if self.document.get(base.id) is not None else []
                self.update_bool_status()
        self.run_operation('Operacja na bryłach', build, apply, after=again)

    # =====================================================================
    # edytuj bryłę: zaokrąglenia i fazy z uchwytem-strzałką
    # =====================================================================
    def _mod_kind_changed(self, *_):
        fillet = self.mod_kind.currentData() == 'fillet'
        self.mod_label.setText('Promień zaokrąglenia (mm)' if fillet else 'Odległość fazy (mm)')
        self.mod_size_pic.setPixmap(ui.icons.pixmap('md_fillet' if fillet else 'md_chamfer', 48))
        self._timers['mod'].start()

    def _mod_value_changed(self):
        self._timers['mod'].start()
        if self._hv is None:
            self._place_mod_handle()

    def pick_edge(self, x, y, shift, ctrl):
        vertex = self.view.nearest_vertex(x, y)
        if vertex is not None:       # sam narożnik: faza / zaokrąglenie rogu (krawędzie zostają ostre)
            bid, point = vertex
            body = self.document.get(bid)
            if body is None or body.kind != 'solid':
                return
            self._mod_vertex_select(bid, np.asarray(point, float), shift, ctrl)
            return
        hit = self.view.nearest_edge(x, y, True)
        if hit is None:
            self.update_mod_status()          # kliknięcie obok nie kasuje wybranych krawędzi i narożników
            return
        bid, index = hit[0], hit[1]
        body = self.document.get(bid)
        if body is None or body.kind != 'solid':
            return
        self._mod_select(bid, set(kernel.edge_chain(body.shape, index)) if ctrl else {index}, shift, ctrl, mark=index)

    def _mod_reset_size(self):
        if not any(self.mod_vertices.values()) and not any(self.edges.values()):
            self.mod_size.blockSignals(True)
            self.mod_size.setValue(2.0)
            self.mod_size.blockSignals(False)

    def _mod_vertex_select(self, bid, point, shift, ctrl):
        """Narożnik: kliknięcie dodaje go do wybranych (krawędzie i narożniki, także na innych bryłach), Shift + klik
        odznacza pomyłkowo wybrany."""
        self._mod_reset_size()
        points = self.mod_vertices.setdefault(bid, [])
        same = [q for q in points if float(np.linalg.norm(q - point)) < 1e-3]
        if shift:
            points[:] = [q for q in points if all(q is not r for r in same)]
        elif not same:
            points.append(point)
        self.mod_vertices = {k: v for k, v in self.mod_vertices.items() if v}
        if not shift:self._mod_pick_order=[*getattr(self,'_mod_pick_order',[]),('vertex',bid,tuple(point))]
        self._mod_face_mesh = None
        self.update_mod_status()

    def _mod_select(self, bid, ids, shift, ctrl, mark=None):
        """Krawędzie: kliknięcie dodaje (Ctrl - cały łańcuch stycznych), Shift + klik odznacza pomyłkowo wybrane."""
        self._mod_reset_size()
        self._mod_face_mesh = None
        current = self.edges.setdefault(bid, set())
        if shift:
            current -= ids
        else:
            current |= ids
        self.edges = {k: v for k, v in self.edges.items() if v}
        if not shift:
            picked=mark if mark in ids else max(ids) if ids else None
            if picked is not None:self._mod_pick_order=[*getattr(self,'_mod_pick_order',[]),('edge',bid,picked)]
        self.update_mod_status()

    def _mod_items(self):
        """Zaznaczenie zaokrąglenia / fazy pogrupowane po bryłach: [(id, krawędzie albo None, narożniki albo None)]."""
        out = []
        for bid in dict.fromkeys([*self.edges, *self.mod_vertices]):
            ids = set(self.edges.get(bid) or ())
            pts = [np.array(q, float) for q in (self.mod_vertices.get(bid) or [])]
            if (ids or pts) and self.document.get(bid) is not None:
                out.append((bid, ids or None, pts or None))
        return out

    def view_double_clicked(self, x, y):
        """Podwójne kliknięcie ściany w trybie edycji bryły: podświetla ścianę i zaznacza wszystkie jej krawędzie (zaokrąglenie / faza na okrągło)."""
        if self.busy or self.mode != 'mod':
            return
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            return
        try:
            face, ids = kernel.face_edge_indices(body.shape, hit[2])
            ids = {i for i in ids if i in body.mesh.edges}
            mesh = kernel.display_mesh(face)
        except Exception:
            self.toast('Nie udało się zaznaczyć krawędzi ściany.')
            return
        if not ids:
            return
        if not any(self.edges.values()) and not any(self.mod_vertices.values()):
            self.mod_size.blockSignals(True)
            self.mod_size.setValue(2.0)
            self.mod_size.blockSignals(False)
        nearest=min(ids,key=lambda i:body.shape.Edges()[i].distance(cq.Vertex.makeVertex(*map(float,hit[2]))))
        self.edges=dict(self.edges);self.edges[body.id]=set(self.edges.get(body.id,()))|ids
        self._mod_pick_order=[*getattr(self,'_mod_pick_order',[]),('edge',body.id,nearest)]
        self._mod_face_mesh = None          # zaznaczają się krawędzie obwodu; sama ściana się nie podświetla (widać tworzone zaokrąglenie)
        self.update_mod_status()

    def update_mod_status(self):
        count = sum(len(v) for v in self.edges.values())
        vcount = sum(len(v) for v in self.mod_vertices.values())
        self.mod_status.setText(self._mod_count_text() if count or vcount else
                                'Klikaj krawędzie i narożniki - każde kliknięcie dodaje kolejne (także na innych bryłach); Shift + klik odznacza pomyłkowo wybrane; dwuklik w ścianę dodaje cały jej obwód.')
        self.view.sel_vertices = [np.asarray(q, float) for pts in self.mod_vertices.values() for q in pts]
        count += vcount
        if not count:
            self.view.sel_vertices = []
            self._mod_face_mesh = None
        self.view.set_selection_meshes([self._mod_face_mesh] if self._mod_face_mesh is not None and count else None)
        self.refresh()
        self._place_mod_handle()
        self._timers['mod'].start()

    def _mod_count_text(self):
        count = sum(len(v) for v in self.edges.values())
        vcount = sum(len(v) for v in self.mod_vertices.values())
        parts = ([f'krawędzie: {count}'] if count else []) + ([f'narożniki: {vcount}'] if vcount else [])
        bodies = len(self._mod_items())
        return 'Zaznaczone ' + ', '.join(parts) + (f' (bryły: {bodies})' if bodies > 1 else '')

    def _place_mod_handle(self):
        if self.mode!='mod':self.view.set_handles([]);return
        order=[]
        for kind,bid,value in getattr(self,'_mod_pick_order',[]):
            alive=(value in self.edges.get(bid,())) if kind=='edge' else any(np.linalg.norm(np.asarray(value)-q)<1e-3 for q in self.mod_vertices.get(bid,()))
            if alive and self.document.get(bid) is not None:order.append((kind,bid,value))
        self._mod_pick_order=order
        if order:kind,bid,value=order[-1]
        elif any(self.edges.values()):
            bid,ids=next((bid,ids) for bid,ids in reversed(list(self.edges.items())) if ids);kind,value='edge',max(ids)
        elif self.mod_vertices:
            bid,points=next(iter(reversed(list(self.mod_vertices.items()))));kind,value='vertex',points[-1]
        else:self.view.set_handles([]);return
        body=self.document.get(bid)
        try:
            hkey=(id(body.shape),kind,tuple(value) if kind=='vertex' else value)
            cached=getattr(self,'_mod_handle',None)
            if cached is None or cached[0]!=hkey:
                result=kernel.vertex_handle(body.shape,value) if kind=='vertex' else kernel.edge_handle(body.shape,value)
                cached=self._mod_handle=(hkey,result)
            mid,direction=cached[1]
        except Exception:self.view.set_handles([]);return
        mid=np.asarray(mid,float);d=np.asarray(direction,float)
        self.view.set_handles([dict(id='mod',start=mid,tip=mid+d*self.mod_size.value(),dir=d,color=(.94,.6,.13,1))])
    def update_mod_preview(self):
        if self.mode != 'mod':
            return
        items = self._mod_items()
        if not items:
            self.cancel_previews()
            self.view.set_preview_mesh(None)
            return
        if len(items) > 1 or (items[0][1] and items[0][2]):
            self._mod_multi_preview(items)
            return
        verts = bool(items[0][2])
        if verts:
            bid, pts = next(iter(self.mod_vertices.items()))
            sig, count, label = ('v', bid, tuple(tuple(np.round(q, 3)) for q in pts)), len(pts), 'narożniki'
            ids = None
        else:
            bid, ids = next(iter(self.edges.items()))
            ids = set(ids)
            sig, count, label = ('e', bid, frozenset(ids)), len(ids), 'krawędzie'
        body = self.document.get(bid)
        if body is None:
            return
        size, kind = self.mod_size.value(), self.mod_kind.currentData()
        self._mod_sig = sig
        points = [np.array(q, float) for q in (self.mod_vertices.get(bid) or [])] if verts else None

        margin = max(4.0 * size, 2.0)
        shape = body.shape
        # natychmiast: analityczny podgląd (proste krawędzie między płaskimi ścianami); dokładny dochodzi w tle
        quick = None
        if not verts:
            try:
                fkey = (bid, id(shape), frozenset(ids))
                cached = getattr(self, '_mod_frames', None)
                if not cached or cached[0] != fkey:
                    cached = self._mod_frames = (fkey, kernel.blend_frames(shape, ids))
                quick = kernel.quick_blend_mesh(shape, ids, size, kind, frames=cached[1]) if cached[1] else None
            except Exception:
                quick = None
            if quick is not None:
                self.view.set_preview_mesh(quick, color=MOD_PREVIEW, line_color=MOD_PREVIEW_LINE, width=2.2, on_top=True)
                self.mod_status.setText(f'Zaznaczone {label}: {count}')
        token = (bid, id(shape))

        def compute():
            if workers.ready():
                for attempt in range(2):
                    sent = getattr(self, '_mod_sent', None) == token and attempt == 0
                    try:
                        mesh = workers.call_affine(('mod',), hist.mod_preview_job, token, None if sent else shape,
                                                   None if verts else sorted(ids), points, size, kind, margin)
                        self._mod_sent = token
                        return mesh
                    except workers.Unavailable as exc:
                        self._mod_sent = None
                        if isinstance(exc.__cause__, LookupError):
                            continue                 # proces nie pamięta bryły: wysyła się ją jeszcze raz
                        break
            cache = getattr(self, '_mod_cache', None)
            if cache is None or cache.get('token') != token:
                cache = self._mod_cache = {'token': token}
            return hist.mod_preview(shape, None if verts else ids, points, size, kind, margin, cache)

        def show(value, error):
            if self.mode != 'mod' or getattr(self, '_mod_sig', None) != sig:
                return
            if error or value is None:
                self.view.set_preview_mesh(None)
                self.mod_status.setText(f'Zaznaczone {label}: {count}\n' + (str(error) if verts and error else 'Ta wartość jest za duża dla wybranych elementów.'))
                return
            # tylko tworzona powierzchnia, ciepły fiolet, widoczna także przez jeszcze ostry narożnik bryły
            self.view.set_preview_mesh(value, color=MOD_PREVIEW, line_color=MOD_PREVIEW_LINE, width=2.2, on_top=True)
            self.mod_status.setText(f'Zaznaczone {label}: {count}')

        self.run_preview('mod', compute, show)
    def _mod_multi_preview(self, items):
        """Podgląd dla kilku brył albo krawędzi i narożników naraz: liczony w procesie w tle, tylko nowe powierzchnie."""
        size, kind = self.mod_size.value(), self.mod_kind.currentData()
        sig = ('m', tuple((bid, frozenset(ids or ()), tuple(tuple(np.round(q, 3)) for q in (pts or ()))) for bid, ids, pts in items), size, kind)
        self._mod_sig = sig
        jobs = [(self.document.get(bid).shape, sorted(ids) if ids else None, pts) for bid, ids, pts in items]
        text = self._mod_count_text()

        def compute():
            return hist.background(hist.mod_preview_many, jobs, size, kind, max(4.0 * size, 2.0))

        def show(value, error):
            if self.mode != 'mod' or getattr(self, '_mod_sig', None) != sig:
                return
            if error or value is None:
                self.view.set_preview_mesh(None)
                self.mod_status.setText(text + '\nTa wartość jest za duża dla wybranych elementów.')
                return
            self.view.set_preview_mesh(value, color=MOD_PREVIEW, line_color=MOD_PREVIEW_LINE, width=2.2, on_top=True)
            self.mod_status.setText(text)

        self.run_preview('mod', compute, show)

    def apply_mod(self):
        if self.busy:
            return
        items = self._mod_items()
        if not items:
            self.toast('Zaznacz krawędzie lub narożniki.')
            return
        if len(items) > 1 or (items[0][1] and items[0][2]):
            self._apply_mod_many(items)
            return
        verts = bool(items[0][2])
        if verts:
            bid, pts = next(iter(self.mod_vertices.items()))
            points, ids = [np.array(q, float) for q in pts], None
        else:
            bid, ids = next(iter(self.edges.items()))
            ids, points = set(ids), None
        body = self.document.get(bid)
        size, kind = self.mod_size.value(), self.mod_kind.currentData()

        def recipe_of():      # odwołania do krawędzi / narożników liczone w tle, razem z operacją (nie blokują interfejsu)
            return dict(type='mod', id=body.id, kind=kind, size=size, verts=[[float(c) for c in q] for q in points] if verts else [], vrefs=hist.vertex_refs(body.shape, points) if verts else [],
                        edges=[] if verts else hist.edge_refs(body.shape, ids))

        def apply(result):
            new, recipe = result
            self.document.pending_op = recipe
            self.document.commit([new if b.id == body.id else b for b in self.document.bodies])
            self._tool_select([body.id])

        self.view.set_preview_mesh(None)
        self.view.set_handles([])
        # zaokrąglenie / faza liczy proces liczący - okno w tym czasie działa (obracanie, oglądanie modelu)
        work = (lambda: (body.changed(*hist.offloaded_shape(kernel.blend_vertices, body.shape, points, size, kind)), recipe_of())) if verts else \
            (lambda: (body.changed(*hist.offloaded_shape(kernel.blend, body.shape, ids, size, kind)), recipe_of()))
        self.run_operation('Zaokrąglanie' if kind == 'fillet' else 'Fazowanie', work, apply, after=lambda: self.set_mode(None))

    def _apply_mod_many(self, items):
        """Kilka brył albo krawędzie razem z narożnikami - jeden krok historii, liczony w procesie w tle."""
        size, kind = self.mod_size.value(), self.mod_kind.currentData()
        bodies = {bid: self.document.get(bid) for bid, _, _ in items}

        def work():
            made, entries = {}, []
            for bid, ids, pts in items:
                body = bodies[bid]
                shape, mesh = hist.offloaded_shape(hist.mod_many_job, body.shape, sorted(ids) if ids else None, pts, size, kind)
                made[bid] = body.changed(shape, mesh) if mesh is not None else body.changed(shape)
                entries.append(dict(id=bid, edges=hist.edge_refs(body.shape, ids) if ids else [],
                                    verts=[[float(c) for c in q] for q in pts] if pts else [],
                                    vrefs=hist.vertex_refs(body.shape, pts) if pts else []))
            return made, dict(type='mod', kind=kind, size=size, items=entries)

        def apply(result):
            made, recipe = result
            self.document.pending_op = recipe
            self.document.commit([made.get(b.id, b) for b in self.document.bodies])
            self._tool_select(list(made))

        self.view.set_preview_mesh(None)
        self.view.set_handles([])
        self.run_operation('Zaokrąglanie' if kind == 'fillet' else 'Fazowanie', work, apply, after=lambda: self.set_mode(None))

    # =====================================================================
    # lustro
    # =====================================================================
    # =====================================================================
    # przetnij bryłę: płaszczyzną, ścianą, szkicem albo inną bryłą
    # =====================================================================
    def reset_split(self):
        self.sp_id, self.sp_ref = None, None
        self.view.tints = {}
        self.cancel_previews()
        self.view.set_preview_mesh(None)
        self.view.set_handles([])
        self.update_split_status()

    def _split_method_changed(self):
        method = self.sp_method.currentData()
        self.sp_ref = None
        self.sp_plane_box.setVisible(method == 'plane')
        self.sp_step2.setVisible(method != 'plane')
        self.sp_offset_box.setVisible(method in ('plane', 'face'))
        self.sp_step2.title.setText({'face': 'Ściana cięcia', 'sketch': 'Szkic cięcia', 'body': 'Bryła tnąca'}.get(method, ''))
        self.sp_offset.blockSignals(True)
        self.sp_offset.setValue(0)
        self.sp_offset.blockSignals(False)
        if self.sp_panel.isVisible():
            self.sp_panel.adjustSize()
        self.update_split_status()

    def _split_hover(self, x, y):
        """Przecinanie: to, co zostanie wskazane kliknięciem, podświetla się pod kursorem (bryła, ściana, szkic, bryła tnąca)."""
        method = self.sp_method.currentData()
        if self.sp_id is not None and method == 'face':
            self.view.set_hover_body(None)
            self._sp_hover = None
            self._hover_face_only(x, y)
            return
        if self.sp_id is not None and method == 'sketch':
            hit = self.view.nearest_edge(x, y, kinds=('sketch',))
            bid = hit[0] if hit else None
            body = self.document.get(bid) if bid else None
            bid = bid if body is not None and body.kind == 'sketch' else None
        else:
            bid = self.pick_object(x, y)
            body = self.document.get(bid) if bid else None
            ok = body is not None and body.kind == 'solid' and (self.sp_id is None or method == 'plane' or (method == 'body' and body.id != self.sp_id))
            bid = bid if ok else None
        if getattr(self, '_sp_hover', None) != bid:
            self._sp_hover = bid
            body = self.document.get(bid) if bid else None
            sketch = body is not None and body.kind == 'sketch'
            self.view.set_hover_body(bid if sketch else None)
            if body is not None and not sketch and body.mesh is not None:
                self.view.set_selection_meshes([body.mesh], color=(1, .55, .1, .35), line_color=(.95, .42, .02, 1))
            else:
                self.view.set_selection_meshes(None)
        self.view.setCursor(Qt.PointingHandCursor if bid else Qt.ArrowCursor)

    def pick_split(self, x, y):
        self._sp_hover = None
        self.view.set_hover_body(None)
        self.view.set_selection_meshes(None)
        method = self.sp_method.currentData()
        if self.sp_id is None or method == 'plane':
            bid = self.pick_object(x, y)
            body = self.document.get(bid) if bid else None
            if body is None or body.kind != 'solid':
                if self.sp_id is None:
                    self.toast('Kliknij bryłę, którą chcesz przeciąć.')
                return
            self.sp_id = body.id
            self.update_split_status()
            return
        if method == 'face':
            hit = self.view.pick_face(x, y)
            body = self.document.get(hit[0]) if hit else None
            if body is None or body.kind != 'solid':
                self.toast('Kliknij płaską ścianę - jej płaszczyzna przetnie bryłę.')
                return
            try:
                face, normal = self.view.face_at(body,hit)
            except kernel.CadError as exc:
                self.toast(str(exc))
                return
            self.sp_ref = dict(normal=[float(c) for c in normal], origin=[float(c) for c in face.Center().toTuple()])
        else:
            bid = self.pick_object(x, y)
            body = self.document.get(bid) if bid else None
            want = 'sketch' if method == 'sketch' else 'solid'
            if body is None or body.kind != want or body.id == self.sp_id:
                self.toast('Kliknij szkic (linię, łuk albo zamknięty profil).' if method == 'sketch' else 'Kliknij inną bryłę, która przecina tę bryłę.')
                return
            self.sp_ref = dict(tool=body.id, name=body.name)
        self.update_split_status()

    def _split_recipe(self):
        """Przepis cięcia z bieżących ustawień albo None, gdy czegoś brakuje."""
        body = self.document.get(self.sp_id) if self.sp_id else None
        if body is None:
            return None
        method = self.sp_method.currentData()
        recipe = dict(type='split', id=body.id, method=method, keep=self.sp_keep.currentData())
        if method == 'plane':
            name = self.sp_plane.currentData()
            normal = {'XY': (0, 0, 1), 'XZ': (0, -1, 0), 'YZ': (1, 0, 0)}[name]
            recipe.update(plane=name, normal=[float(c) for c in normal], origin=[float(c) for c in _center(body.shape).toTuple()],
                          offset=float(self.sp_offset.value()))
        elif self.sp_ref is None:
            return None
        elif method == 'face':
            recipe.update(normal=self.sp_ref['normal'], origin=self.sp_ref['origin'], offset=float(self.sp_offset.value()))
        else:
            recipe.update(tool=self.sp_ref['tool'])
        return recipe

    def update_split_status(self):
        body = self.document.get(self.sp_id) if self.sp_id else None
        method = self.sp_method.currentData()
        if body is None:
            self.sp_step1.set_state('active', 'Kliknij bryłę')
            self.sp_step2.set_state('pending', 'Najpierw wybierz bryłę')
            self.view.tints = {}
        else:
            self.sp_step1.set_state('done', body.name)
            self._tint_targets(body.id, ('solid',), exclude=((self.sp_ref or {}).get('tool'),))
            many = len(self.view.tints)
            if many > 1:
                self.sp_step1.set_state('done', f'{body.name} + {many - 1} zaznaczone')
            if self.sp_ref is None:
                self.sp_step2.set_state('active', {'face': 'Kliknij płaską ścianę', 'sketch': 'Kliknij szkic', 'body': 'Kliknij bryłę tnącą'}.get(method, ''))
            else:
                self.sp_step2.set_state('done', self.sp_ref.get('name', 'Wskazana'))
        self.refresh()
        self._place_split_handle()
        self._timers['split'].start()

    def _split_frame(self):
        """(normalna, punkt na płaszczyźnie cięcia z odsunięciem) dla metod z płaszczyzną."""
        recipe = self._split_recipe()
        if recipe is None or recipe['method'] not in ('plane', 'face'):
            return None
        n = np.array(recipe['normal'], float)
        n = n / np.linalg.norm(n)
        return n, np.array(recipe['origin'], float) + n * recipe['offset']

    def _place_split_handle(self):
        frame = self._split_frame() if self.mode == 'split' else None
        body = self.document.get(self.sp_id) if self.sp_id else None
        if frame is None or body is None:
            self.view.set_handles([])
            return
        n, origin = frame
        c = np.array(_center(body.shape).toTuple(), float)
        start = c - n * float((c - origin) @ n)
        b = kernel.bounds(body.shape)
        length = max(b.xlen, b.ylen, b.zlen) * .35
        self.view.set_handles([dict(id='split', start=start, tip=start + n * length, dir=n, color=(.94, .6, .13, 1))])

    def update_split_preview(self):
        if self.mode != 'split':
            return
        recipe = self._split_recipe()
        if recipe is None:
            self.cancel_previews()
            self.view.set_preview_mesh(None)
            self.sp_status.setText('')
            return
        existing = list(self.document.bodies)
        sig = json.dumps(recipe, sort_keys=True)
        self._sp_sig = sig

        def compute():
            return hist.background(hist.split_preview, hist.light(existing), recipe, PREVIEW_TOL)

        def show(value, error):
            if self.mode != 'split' or getattr(self, '_sp_sig', None) != sig:
                return
            if error or value is None:
                self.view.set_preview_mesh(None)
                self.sp_status.setText(str(error) if error else '')
                return
            meshes, cut = value
            self.view.set_split_preview(meshes, cut)
            count = sum(1 for *_, kept in meshes if kept)
            self.sp_status.setText(f'Części po przecięciu: {len(meshes)}' + ('' if recipe['keep'] == 'both' else f', zostaje: {count}'))

        self.run_preview('split', compute, show)

    def apply_split(self):
        if self.busy:
            return
        recipe = self._split_recipe()
        if recipe is None:
            self.toast('Kliknij bryłę i wskaż, czym ją przeciąć.')
            return
        recipe['out'] = uuid.uuid4().hex
        targets = self._multi_targets(recipe['id'], ('solid',), exclude=(recipe.get('tool'),))
        if len(targets) > 1:          # kilka zaznaczonych: każda przecięta tym samym (płaszczyzna - przez środek każdej)
            steps = []
            for i in targets:
                step = dict(recipe, id=i, out=uuid.uuid4().hex)
                if recipe['method'] == 'plane':
                    step['origin'] = [float(c) for c in _center(self.document.get(i).shape).toTuple()]
                steps.append(step)
            self._run_multi('Przecięcie', 'split', steps)
            return
        existing = list(self.document.bodies)

        def build():
            return list(hist.offloaded(hist.run_split, existing, recipe))

        def apply(new):
            self.document.pending_op = recipe
            self.document.commit(new)

        self.view.set_preview_mesh(None)
        self.view.set_handles([])
        self.run_operation('Przecięcie', build, apply, after=lambda: self.set_mode(None))

    def reset_mirror(self):
        self.mirror_id = None
        self.mirror_frame = None
        self.view.tints = {}
        self.view.set_preview_mesh(None)
        self.update_mirror_status()

    def pick_mirror(self, x, y):
        if self.mirror_id is None:
            bid = self.pick_object(x, y)
            if bid is None:
                self.toast('Kliknij bryłę lub element szkicu do odbicia.')
                return
            self.mirror_id = bid
            self._tint_targets(bid, ('solid', 'sketch'))
            self.update_mirror_status()
            return
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij ścianę, względem której ma nastąpić odbicie.')
            return
        try:
            face, normal = self.view.face_at(body,hit)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        self.mirror_frame = (tuple(float(c) for c in normal), tuple(float(c) for c in face.Center().toTuple()))
        self.view.set_selection_meshes([kernel.display_mesh(face)], color=(.25, .75, .45, .55), line_color=(.1, .55, .3, 1))
        self.update_mirror_status()

    # =====================================================================
    # dopasowanie (ściana do ściany) i wyrównanie (ściany na jednej wysokości)
    # =====================================================================
    def spin_mate(self, step):
        """Dopasowanie: obrót przesuwanej bryły o step stopni wokół osi prostopadłej do ścian (przez ich wspólny środek)."""
        if self.mode != 'mate':
            return
        self.mt_spin = (getattr(self, 'mt_spin', 0.0) + float(step)) % 360.0
        shown = self.mt_spin if self.mt_spin <= 180 else self.mt_spin - 360
        self.mt_angle.setText(f'{shown:+.0f}°'.replace('+0°', '0°'))
        if 'moving' in self.mt_pick and 'target' in self.mt_pick:
            self.update_mate_preview()
        else:
            self.mt_status['mate'].setText('Obrót zostanie użyty po wskazaniu obu ścian.')

    def _mt_reset(self):
        self.mt_pick = {}
        self.mt_spin = 0.0
        if hasattr(self, 'mt_angle'):
            self.mt_angle.setText('0°')
        self.view.set_preview_mesh(None)
        self._mt_update()

    def pick_mate(self, x, y):
        """Pierwsze kliknięcie: ściana przesuwanej bryły, drugie: ściana innej bryły. Kliknięcie ściany przesuwanej bryły
        zmienia jej ścianę, kliknięcie ściany innej bryły - ścianę docelową."""
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij płaską ścianę bryły.')
            return
        try:
            face, normal = self.view.face_at(body,hit)
        except kernel.CadError:
            self.toast('Wybierz płaską ścianę.')
            return
        normal = hist.outward_normal(body.shape, face, normal)
        pick = dict(id=body.id, face=face, normal=tuple(float(c) for c in normal), point=tuple(float(c) for c in hit[2]))
        moving = self.mt_pick.get('moving')
        if moving is None or body.id == moving['id']:
            self.mt_pick['moving'] = pick
            if moving is not None and moving['id'] != body.id:
                self.mt_pick.pop('target', None)
        else:
            self.mt_pick['target'] = pick
        self._hover_key = None
        self._mt_update()

    def _mt_recipe(self):
        mv, tg = self.mt_pick.get('moving'), self.mt_pick.get('target')
        if mv is None or tg is None:
            return None
        a, b = self.document.get(mv['id']), self.document.get(tg['id'])
        recipe = dict(type='mate', mode=self.mode, id=a.id, target=b.id,
                      face=hist.face_ref(mv['face'], mv['normal'], mv['point'], a.shape),
                      tface=hist.face_ref(tg['face'], tg['normal'], tg['point'], b.shape))
        if self.mode == 'mate' and getattr(self, 'mt_spin', 0.0):
            recipe['spin'] = float(self.mt_spin)
        return recipe

    def _mt_update(self):
        if self.mode not in ('mate', 'align'):
            return
        mv, tg = self.mt_pick.get('moving'), self.mt_pick.get('target')
        steps, status = self.mt_steps[self.mode], self.mt_status[self.mode]
        a = self.document.get(mv['id']) if mv else None
        b = self.document.get(tg['id']) if tg else None
        steps[0].set_state('done' if a else 'active', a.name if a else 'Kliknij ścianę')
        steps[1].set_state('done' if b else ('active' if a else 'pending'), b.name if b else ('Ściana innej bryły' if a else 'Najpierw krok 1'))
        self.view.tints = {**({a.id: TINT_TOOL} if a else {}), **({b.id: TINT_BASE} if b else {})}
        meshes = [kernel.display_mesh(p['face']) for p in (mv, tg) if p]
        self.view.set_selection_meshes(meshes)
        status.setText('Zastosuj (Enter) przesuwa pierwszą bryłę.' if b else ('Teraz kliknij ścianę innej bryły.' if a else 'Kliknij ścianę bryły, która ma się przesunąć.'))
        self.refresh()
        self.update_mate_preview()

    def update_mate_preview(self):
        recipe = self._mt_recipe() if self.mode in ('mate', 'align') else None
        if recipe is None:
            return
        bodies = tuple(self.document.bodies)
        mode = self.mode

        def compute():
            return hist.background(hist.recipe_body_mesh, hist.light(bodies), recipe, PREVIEW_TOL)

        def show(mesh, error):
            if self.mode != mode:
                return
            if error:
                self.view.set_preview_mesh(None)
                self.mt_status[mode].setText(error)
                return
            self.view.set_preview_mesh(mesh, color=(.3, .8, .5, .5), line_color=(.05, .4, .2, 1), width=2)

        self.run_preview('mate', compute, show)

    def apply_mate(self):
        if self.busy or self.mode not in ('mate', 'align'):
            return
        recipe = self._mt_recipe()
        if recipe is None:
            self.toast('Kliknij ścianę bryły do przesunięcia, a potem ścianę drugiej bryły.')
            return
        existing = tuple(self.document.bodies)
        label = 'Dopasowanie' if recipe['mode'] == 'mate' else 'Wyrównanie'

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.commit(list(bodies))
            self._tool_select([recipe['id']])

        self.view.set_preview_mesh(None)
        self.run_operation(label, lambda: hist.offloaded(hist.run_recipe, existing, recipe), apply, after=lambda: self.set_mode(None))

    def update_mirror_status(self):
        body = self.document.get(self.mirror_id) if self.mirror_id else None
        if body is None:
            self.mir_step1.set_state('active', 'Kliknij bryłę lub szkic')
            self.mir_step2.set_state('pending', 'Najpierw wybierz obiekt')
        elif self.mirror_frame is None:
            self.mir_step1.set_state('done', body.name)
            self.mir_step2.set_state('active', 'Kliknij ścianę bryły')
        else:
            self.mir_step1.set_state('done', body.name)
            self.mir_step2.set_state('done', 'Wskazana')
        self.mir_join.setEnabled(body is not None and body.kind == 'solid')
        self.refresh()
        self._timers['mirror'].start()

    def update_mirror_preview(self):
        if self.mode != 'mirror':
            return
        if self.mirror_id is None or self.mirror_frame is None:
            self.cancel_previews()
            self.view.set_preview_mesh(None)
            return
        body = self.document.get(self.mirror_id)
        frame = self.mirror_frame

        def compute():
            return hist.background(hist.mesh_of, kernel.mirror_plane, (body.shape, *frame), PREVIEW_TOL)

        def show(mesh, error):
            if self.mode == 'mirror' and self.mirror_frame == frame:
                self.view.set_preview_mesh(None if error else mesh, color=(.3, .8, .5, .55), line_color=(.05, .4, .2, 1), width=2)

        self.run_preview('mirror', compute, show)
    def apply_mirror(self):
        if self.busy:
            return
        if self.mirror_id is None or self.mirror_frame is None:
            self.toast('Kliknij obiekt, a potem ścianę jako płaszczyznę odbicia.')
            return
        body = self.document.get(self.mirror_id)
        normal, origin = self.mirror_frame
        keep, join = self.mir_keep.isChecked(), self.mir_join.isChecked() and body.kind == 'solid'

        recipe = dict(type='mirror', id=body.id, normal=[float(c) for c in normal], origin=[float(c) for c in origin], keep=keep, join=join, out=uuid.uuid4().hex)
        targets = self._multi_targets(body.id, ('solid', 'sketch'))
        if len(targets) > 1:          # kilka zaznaczonych: każdy odbity względem tej samej płaszczyzny
            steps = [dict(recipe, id=i, join=join and self.document.get(i).kind == 'solid', out=uuid.uuid4().hex) for i in targets]
            self._run_multi('Odbicie lustrzane', 'mirror', steps, [st['out'] if keep and not st['join'] else st['id'] for st in steps])
            return
        existing = list(self.document.bodies)

        def build():
            return list(hist.offloaded(hist.run_mirror, existing, recipe))

        def apply(new):
            self.document.pending_op = recipe
            self.document.commit(new)
            self._tool_select([new[-1].id if keep and not join else body.id])

        self.view.set_preview_mesh(None)
        self.run_operation('Odbicie lustrzane', build, apply, after=lambda: self.set_mode(None))

    # =====================================================================
    # szyk: prostokątny / kołowy / wzdłuż linii (szkice i bryły), podgląd na żywo bez OCC
    # =====================================================================
    def reset_pattern(self):
        self.pat_id, self.pat_path = None, None
        self.view.tints = {}
        self.view.set_preview_mesh(None)
        self.view.set_selection_meshes(None)
        self.update_pattern_status()

    def _pattern_kind_changed(self):
        kind = self.pat_kind.currentData()
        self.pat_rect.setVisible(kind == 'rect')
        self.pat_circ.setVisible(kind == 'circ')
        self.pat_line.setVisible(kind == 'path')
        self.pat_step2.setVisible(kind == 'path')
        self.pat_panel.adjustSize()
        self.update_pattern_status()

    @staticmethod
    def _mesh_bounds(mesh):
        pts = mesh.vertices if len(mesh.vertices) else np.concatenate([e.reshape(-1, 3) for e in mesh.edges.values()])
        return np.min(pts, axis=0), np.max(pts, axis=0)

    def _pattern_candidate(self, x, y):
        """Co zostanie wybrane pod kursorem: bid obiektu lub None. Szkic ma pierwszeństwo przed bryłą (chyba że filtr mówi inaczej)."""
        mode = self.pat_filter.currentData()
        if mode in ('auto', 'sketch'):
            hit = self.view.nearest_edge(x, y, kinds=('sketch',))
            if hit:
                return hit[0]
            if mode == 'sketch':
                return self.view.pick_profile(x, y)
        solid = self.view.pick_body(x, y)
        if solid is not None and (mode == 'solid' or (self.document.get(solid) is not None and self.document.get(solid).kind == 'solid')):
            return solid
        if mode == 'solid':
            hit = self.view.nearest_edge(x, y, True)
            return hit[0] if hit else None
        return solid

    def _pattern_hover(self, x, y):
        bid = self._pattern_candidate(x, y)
        body = self.document.get(bid) if bid else None
        if getattr(self, '_pat_hover_id', 0) != bid:
            self._pat_hover_id = bid
            self.view.set_hover_body(bid if body is not None and body.kind == 'sketch' else None)
            if body is not None and body.kind == 'solid' and body.mesh is not None:
                self.view.set_selection_meshes([body.mesh], color=(1, .55, .1, .35), line_color=(.95, .42, .02, 1))
            else:
                self.view.set_selection_meshes(None)
            if body is None:
                self.pat_step1.set_state('active', 'Kliknij bryłę lub szkic')
            else:
                self.pat_step1.set_state('active', ('Szkic: ' if body.kind == 'sketch' else 'Bryła: ') + body.name)
        self.view.setCursor(Qt.PointingHandCursor if body is not None else Qt.ArrowCursor)

    def pick_pattern(self, x, y):
        if self.pat_id is None:
            bid = self._pattern_candidate(x, y)
            self.view.set_hover_body(None)
            self.view.set_selection_meshes(None)
            self._pat_hover_id = 0
            body = self.document.get(bid) if bid else None
            if body is None or body.mesh is None:
                self.toast('Kliknij bryłę lub szkic, który ma być powielony.')
                return
            self.pat_id = bid
            self._tint_targets(bid, ('solid', 'sketch'))
            low, high = self._mesh_bounds(body.mesh)
            for spin, size in zip(self.pat_gaps, high - low):      # domyślny odstęp: wymiar obiektu + zapas
                spin.blockSignals(True)
                spin.setValue(round(float(size) * 1.25 + 1.0, 1))
                spin.blockSignals(False)
            self.pat_join.setChecked(False)
            self._pattern_defaults(body)
            self.update_pattern_status()
            return
        if self.pat_picking:
            self._pattern_pick_point(x, y)
            return
        if self.pat_kind.currentData() == 'path':
            hit = self.view.nearest_edge(x, y)
            if hit is None:
                self.toast('Kliknij linię szkicu lub krawędź bryły jako ścieżkę.')
                return
            body = self.document.get(hit[0])
            points = body.mesh.edges.get(hit[1]) if body is not None and body.mesh is not None else None
            if points is None or len(points) < 2:
                return
            self.pat_path = np.asarray(points, float)
            ends = self.pat_path[[0, -1]]
            mesh = kernel.DisplayMesh(np.zeros((0, 3), np.float32), np.zeros((0, 3), np.uint32), {0: self.pat_path.astype(np.float32)}, tuple(ends[0]), 1.0)
            self.view.set_selection_meshes([mesh], color=(.3, .8, .5, .5), line_color=(.1, .6, .3, 1))
            self.update_pattern_status()

    def update_pattern_status(self):
        body = self.document.get(self.pat_id) if self.pat_id else None
        path = self.pat_kind.currentData() == 'path'
        if body is None:
            self.pat_step1.set_state('active', 'Kliknij bryłę lub szkic')
            self.pat_step2.set_state('pending', 'Najpierw wybierz obiekt')
        else:
            self.pat_step1.set_state('done', body.name)
            self.pat_step2.set_state('done' if self.pat_path is not None else 'active', 'Wskazana' if self.pat_path is not None else 'Kliknij linię lub krawędź')
        solid = body is None or body.kind == 'solid'
        for axis, pic in zip('XYZ', self.pat_axis_pics):
            pic.setToolTip(f'Oś {axis} świata' if solid else
                           (f'Kierunek {axis} w płaszczyźnie szkicu' if axis != 'Z' else 'Prostopadle do płaszczyzny szkicu'))
        self.pat_join.setEnabled(body is not None and body.kind == 'solid')
        self.pat_result._buttons[2].setEnabled(solid)          # „Jedna bryła” tylko dla brył
        if not solid and self.pat_result.currentData() == 'join':
            self.pat_result.setCurrentIndex(0)
        if body is None or (path and self.pat_path is None):
            self.pat_status.setText('Wybierz obiekt.' if body is None else 'Wskaż ścieżkę.')
        self.refresh()
        self._timers['pattern'].start()

    AXES = {'X': (1.0, 0.0, 0.0), 'Y': (0.0, 1.0, 0.0), 'Z': (0.0, 0.0, 1.0)}

    def _pattern_axes(self, body):
        """Kierunki szyku: dla szkicu - osie jego płaszczyzny (X i Y leżą w płaszczyźnie szkicu, Z to jej normalna), więc kopie
        szkicu na pochylonej ścianie zostają na tej ścianie; dla bryły - osie świata."""
        if body is not None and body.kind == 'sketch':
            try:
                frame = kernel.frame_of(body.plane)
                return {'X': tuple(float(c) for c in kernel._unit(frame.xdir)), 'Y': tuple(float(c) for c in kernel._unit(frame.ydir)),
                        'Z': tuple(float(c) for c in kernel._unit(frame.normal))}
            except Exception:
                pass
        return dict(self.AXES)

    def _pattern_center(self, body):
        low, high = self._mesh_bounds(body.mesh)
        return (low + high) / 2, high - low

    def _radial(self, body):
        """(odległość obiektu od osi, wersor promieniowy) dla bieżącego środka i osi obrotu."""
        axis = np.array(self._pattern_axes(body)[self.pat_axis.currentData()])
        pivot = np.array([s.value() for s in self.pat_pivot], float)
        v = self._pattern_center(body)[0] - pivot
        r = v - float(v @ axis) * axis
        d = float(np.linalg.norm(r))
        if d > 1e-6:
            return d, r / d
        other = np.cross(axis, [0.0, 0.0, 1.0] if abs(axis[2]) < .9 else [1.0, 0.0, 0.0])
        return 0.0, other / np.linalg.norm(other)

    def _pattern_set(self, spins, values):
        for spin, value in zip(spins, values):
            spin.blockSignals(True)
            spin.setValue(round(float(value), 2))
            spin.blockSignals(False)

    def _pattern_defaults(self, body):
        """Domyślny środek: początek układu; gdy obiekt leży na osi, środek przesuwamy tak, by obiekt miał miejsce do obrotu."""
        center, size = self._pattern_center(body)
        self._pattern_set(self.pat_pivot, (0.0, 0.0, 0.0))
        d, direction = self._radial(body)
        if d < 1e-6:
            d = max(float(np.max(size)) * 1.5, 5.0)
            self._pattern_set(self.pat_pivot, center - direction * d)
        self._pattern_set([self.pat_radius], [d])

    def _pattern_pivot_changed(self):
        body = self.document.get(self.pat_id) if self.pat_id else None
        if body is not None and body.mesh is not None:
            self._pattern_set([self.pat_radius], [self._radial(body)[0]])
        self._timers['pattern'].start()

    def _pattern_pick_toggled(self, on):
        self.pat_picking = bool(on) and self.pat_id is not None
        if on and self.pat_id is None:
            self.pat_pick.setChecked(False)
            self.toast('Najpierw wybierz obiekt.')
            return
        if on:
            self.toast('Kliknij dowolny punkt: wierzchołek, ścianę, płaszczyznę lub podłoże - to będzie środek obrotu.', 4000)
        self.view.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    def _pattern_target(self, x, y):
        """Dowolny punkt środka obrotu: wierzchołek (też szkicu), punkt na ścianie, płaszczyzna lub podłoże (z=0)."""
        vertex = self.view.nearest_vertex(x, y, solids_only=False)
        if vertex is not None:
            return np.array(vertex[1], float)
        hit = self.view.pick_face(x, y)
        if hit is not None:
            return np.array(hit[2], float)
        name = self.view.plane_at(x, y)
        found = self.view._plane_hit(name, x, y) if name else None
        if found:
            return np.array(found[1], float)
        ray = self.view._ray(x, y)
        if ray is not None:
            ground = self.view._ray_plane(ray, np.zeros(3), np.array([0.0, 0.0, 1.0]))
            if ground is not None:
                return np.array(ground, float)
        return None

    def _pattern_pick_point(self, x, y):
        point = self._pattern_target(x, y)
        if point is None:
            self.toast('Kliknij dowolny punkt w przestrzeni roboczej.')
            return
        self._pattern_set(self.pat_pivot, point)
        self.view.hover_vertex = None
        self.pat_pick.setChecked(False)
        self._pattern_pivot_changed()

    def _pattern_dir(self, pair, chosen):
        """Kierunek kopii wzdłuż osi: jeden z dwóch przycisków (strzałek) jest zawsze wciśnięty."""
        for b in pair:
            b.setChecked(b is chosen)
        self._timers['pattern'].start()

    def _pattern_spacing(self):
        """Odstępy szyku prostokątnego ze znakiem kierunku (strzałki w panelu)."""
        return [g.value() * next(b.sign for b in pair if b.isChecked()) for g, pair in zip(self.pat_gaps, self.pat_dirs)]

    def _pattern_ops(self, body):
        """(kopie, operacja przesunięcia oryginału na zadaną odległość albo None)."""
        kind = self.pat_kind.currentData()
        if kind == 'rect':
            axes = self._pattern_axes(body)
            return kernel.pattern_ops('rect', dict(counts=[int(round(c.value())) for c in self.pat_counts], spacing=self._pattern_spacing(),
                                                   axes=[axes[a] for a in 'XYZ'])), None
        if kind == 'circ':
            d0, direction = self._radial(body)
            offset = tuple(float(c) for c in direction * (self.pat_radius.value() - d0))
            pivot = tuple(s.value() for s in self.pat_pivot)
            ops = kernel.pattern_ops('circ', dict(axis=self._pattern_axes(body)[self.pat_axis.currentData()], pivot=pivot, count=int(round(self.pat_ccount.value())),
                                                  angle=self.pat_angle.value(), offset=offset))
            return ops, (('t', offset) if max(abs(c) for c in offset) > 1e-9 else None)
        return kernel.pattern_ops('path', dict(points=self.pat_path if self.pat_path is not None else [], count=int(round(self.pat_lcount.value())),
                                               fit=self.pat_fit.isChecked(), spacing=self.pat_lgap.value())), None

    # ---------- gwint ----------
    def _th_standard_changed(self):
        from . import threads as th
        current = self.th_size.currentData()
        self.th_size.blockSignals(True)
        self.th_size.clear()
        for name, d, pitch in th.STANDARDS[self.th_standard.currentData()]['sizes']:
            self.th_size.addItem(f'{name}   (skok {pitch:.3g} mm)', name)
        index = self.th_size.findData(current)
        self.th_size.setCurrentIndex(index if index >= 0 else min(8, self.th_size.count() - 1))
        self.th_size.blockSignals(False)
        self._th_fit()

    def _th_size_changed(self):
        if getattr(self, '_th_auto_set', False):
            return
        if self.th_pick is not None and self.th_auto.isChecked():
            self.th_auto.blockSignals(True)
            self.th_auto.setChecked(False)          # rozmiar wybrany ręcznie: otwór dopasuje się do gwintu
            self.th_auto.blockSignals(False)
        self._th_update()

    def _th_internal(self):
        return self.th_side.currentData() == 'in'

    def _th_fit(self):
        """Automatyczne dopasowanie: rozmiar gwintu do średnicy wybranego otworu / wałka."""
        from . import threads as th
        if self.th_pick is not None and self.th_auto.isChecked():
            name, _ = th.fit(self.th_standard.currentData(), 2 * self.th_pick['info']['radius'], self._th_internal())
            self._th_auto_set = True
            self.th_size.setCurrentIndex(self.th_size.findData(name))
            self._th_auto_set = False
        self._th_update()

    def _th_spec(self, pick=None):
        """Bieżące ustawienia gwintu (bez liczenia geometrii): opis gwintu, docelowa średnica, czy otwór się zmieni.
        pick: inny wybrany walec (Shift) - ten sam gwint, przy automatycznym dopasowaniu rozmiar dobrany do niego."""
        from . import threads as th
        primary = pick is None
        pick = pick or self.th_pick
        if pick is None or self.th_size.currentData() is None:
            return None
        info = dict(pick['info'], internal=self._th_internal() if primary else pick['info']['internal'])
        t0, t1 = info['t0'], info['t1']
        if self.th_extent.currentData() == 'full':
            start, end = t0, t1
        else:
            start = min(t0 + self.th_offset.value(), t1 - .1)
            end = min(start + self.th_length.value(), t1)
        standard, name = self.th_standard.currentData(), self.th_size.currentData()
        if not primary and self.th_auto.isChecked():
            name = th.fit(standard, 2 * info['radius'], info['internal'])[0]
        thread = th.make_thread(info, standard, name, self.th_hand.currentData(), start, end)
        _, d, pitch = th.size(standard, name)
        want = th.bore(standard, d, pitch, info['internal'])
        return dict(info=info, thread=thread, want=want, change=abs(want - 2 * info['radius']) > 1e-3, d=d, pitch=pitch)

    def _th_update(self):
        """Podgląd na żywo: linie gwintu, strzałki długości i rozmiaru, opis - bez tworzenia gwintu w bryle."""
        from . import threads as th
        self.th_len_box.setVisible(self.th_extent.currentData() == 'len')
        if self.th_pick is None:
            self.th_step1.set_state('active', 'Kliknij otwór albo wałek')
        else:
            body = self.document.get(self.th_pick['id'])
            info = self.th_pick['info']
            self.th_step1.set_state('done', f"{'Otwór' if info['internal'] else 'Wałek'} Ø{2 * info['radius']:.2f} · {body.name if body else ''}")
        spec = self._th_spec()
        if spec is None:
            standard = self.th_standard.currentData()
            name = self.th_size.currentData()
            if name:
                _, d, pitch = th.size(standard, name)
                self.th_info.setText(f'{name} · skok {pitch:.3g} mm · otwór Ø{th.drill(standard, d, pitch):g} · wałek Ø{d:g}')
            self.view.set_thread_preview(None)
            self.th_convert.hide()
            if self.mode == 'thread':
                self.view.set_handles([])
            return
        info, thread = spec['info'], spec['thread']
        length = thread['end'] - thread['start']
        kind = 'otwór' if info['internal'] else 'wałek'
        self.th_info.setText(f"{th.label(thread)} · skok {spec['pitch']:.3g} mm · długość {length:.2f} mm\n"
                             f"{kind} Ø{2 * info['radius']:.2f}" + (f" → Ø{spec['want']:.2f}" if spec['change'] else ' (pasuje)'))
        if not self.th_pick['info']['full']:
            self.th_status.setText('To nie jest pełny walec - gwint wymaga pełnego otworu albo wałka.')
        elif spec['change']:
            self.th_status.setText(f"{kind.capitalize()} zostanie dopasowany do gwintu: Ø{2 * info['radius']:.2f} → Ø{spec['want']:.2f} (po Zastosuj).")
        else:
            self.th_status.setText(f'Gwint {th.label(thread)} pasuje do {"otworu" if info["internal"] else "wałka"}. Zastosuj tworzy gwint.')
        extra = [x for x in (self._th_spec(p) for p in self.th_extra) if x is not None]
        self.view.set_thread_preview([thread, *[x['thread'] for x in extra]])
        if extra:
            self.th_status.setText(f'Gwinty na {1 + len(extra)} otworach / wałkach · ' + self.th_status.text())
        body = self.document.get(self.th_pick['id'])
        existing = th.threads_on(body.threads, self.th_pick['info']) if body is not None else []
        self.th_convert.setVisible(bool(existing))
        if existing:
            self.th_convert.setText(f'Zamień wirtualny gwint {th.label(existing[0])} na prawdziwy')
        if self._hv is None:
            self._th_handles(spec)

    def _th_handles(self, spec):
        from . import threads as th
        thread = spec['thread']
        origin, axis = np.asarray(thread['origin'], float), np.asarray(thread['axis'], float)
        helper = np.array([1.0, 0, 0]) if abs(axis[0]) < .9 else np.array([0, 1.0, 0])
        radial = np.cross(axis, helper)
        radial /= np.linalg.norm(radial)
        reach = max(spec['d'] * .8, 4.0)
        a, b = origin + axis * thread['start'], origin + axis * thread['end']
        r = thread['radius']
        mid = origin + axis * (thread['start'] + thread['end']) / 2
        length = thread['end'] - thread['start']
        self.view.set_handles([
            dict(id='thS', start=a + radial * r, tip=a + radial * r - axis * reach, dir=-axis, color=(.95, .55, .12, 1), label=f'{length:.1f}'),
            dict(id='thE', start=b + radial * r, tip=b + radial * r + axis * reach, dir=axis, color=(.95, .55, .12, 1), label=f'{length:.1f}'),
            dict(id='thD', start=mid, tip=mid + radial * (r + reach), dir=radial, color=(.18, .53, .91, 1), label=th.label(thread))])

    def _th_drag(self, hid, delta):
        """Strzałki gwintu: końce zmieniają zakres (przechodzi na „Określona”), strzałka promieniowa - rozmiar gwintu."""
        from . import threads as th
        spec = self._th_spec()
        if spec is None:
            return
        info, thread = spec['info'], spec['thread']
        if self._hv is None or self._hv[0] != hid:
            self._hv = (hid, thread['start'], thread['end'], spec['d'])
        _, start0, end0, d0 = self._hv
        t0, t1 = info['t0'], info['t1']
        if hid == 'thD':
            target = d0 + 2 * delta
            standard = self.th_standard.currentData()
            name = min(th.STANDARDS[standard]['sizes'], key=lambda s: abs(s[1] - target))[0]
            if name != self.th_size.currentData():
                self.th_auto.blockSignals(True)
                self.th_auto.setChecked(False)
                self.th_auto.blockSignals(False)
                self._th_auto_set = True
                self.th_size.setCurrentIndex(self.th_size.findData(name))
                self._th_auto_set = False
            self._th_update()
            return
        if hid == 'thS':
            start, end = min(max(t0, start0 - delta), end0 - .1), end0
        else:
            start, end = start0, max(min(t1, end0 + delta), start0 + .1)
        for w in (self.th_extent, self.th_offset, self.th_length):
            w.blockSignals(True)
        self.th_extent.setCurrentIndex(1)
        self.th_offset.setValue(round(start - t0, 2))
        self.th_length.setValue(round(end - start, 2))
        for w in (self.th_extent, self.th_offset, self.th_length):
            w.blockSignals(False)
        self._th_update()

    def _th_face(self, x, y):
        """Walcowa ściana bryły pod kursorem: (bryła, opis walca) albo None."""
        from . import threads as th
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            return None
        cache = self.__dict__.setdefault('_th_cyl', {})
        key = (body.id, id(body.shape))
        if key not in cache:                     # walce bryły liczone raz - najechanie kursorem to tylko rachunek na liczbach
            if len(cache) > 32:
                cache.clear()
            cache[key] = (body.shape, th.cylinders(body.shape))
        bb = body.mesh.size if body.mesh is not None else 100.0
        info = th.cylinder_at(cache[key][1], hit[2], max(.02, 2e-3 * float(bb)))
        return (body, dict(info)) if info is not None else None

    def _th_hover(self, x, y):
        found = self._th_face(x, y)
        key = ('th', found[0].id, found[1]['index']) if found else None
        if key != self._hover_key:
            self._hover_key = key
            face = found[0].shape.Faces()[found[1]['index']] if found else None
            self.view.set_preview_mesh(kernel.display_mesh(face) if face is not None else None, color=(1, .55, .1, .30), line_color=SKETCH_ORANGE, width=2)

    def pick_thread(self, x, y, shift=False):
        found = self._th_face(x, y)
        if found is None:
            self.th_status.setText('Kliknij walcową ścianę: wnętrze otworu albo powierzchnię wałka.')
            return
        body, info = found
        same = lambda p: p['id'] == body.id and p['info']['index'] == info['index']
        if shift and self.th_pick is not None:
            if same(self.th_pick) or any(same(p) for p in self.th_extra):     # Shift na wybranym: usuń z wyboru
                picks = [p for p in (*self.th_extra, self.th_pick) if not same(p)]
                self.th_extra, self.th_pick = picks[:-1], (picks[-1] if picks else None)
                self._th_update()
                return
            self.th_extra.append(self.th_pick)
        else:
            self.th_extra = []
        self.th_pick = dict(id=body.id, info=info)
        self._hover_key = None
        self.view.set_preview_mesh(None)
        self.th_side.blockSignals(True)
        self.th_side.setCurrentIndex(0 if info['internal'] else 1)
        self.th_side.blockSignals(False)
        self.th_length.blockSignals(True)
        self.th_length.setValue(round(min(self.th_length.value(), info['t1'] - info['t0']) if self.th_extent.currentData() == 'len'
                                      else info['t1'] - info['t0'], 2))
        self.th_length.blockSignals(False)
        self._th_fit()

    def apply_thread(self):
        from . import threads as th
        spec = self._th_spec()
        if spec is None:
            self.toast('Najpierw kliknij otwór albo wałek.')
            return
        if not self.th_pick['info']['full']:
            self.toast('Gwint wymaga pełnego otworu albo wałka.')
            return
        info, thread = spec['info'], spec['thread']

        def item(pick, spec):
            info, thread = spec['info'], spec['thread']
            return dict(id=pick['id'], cylinder=dict(origin=info['origin'], axis=info['axis'], radius=info['radius'], internal=info['internal']),
                        spec=dict(standard=thread['standard'], size=thread['size'], hand=thread['hand'], start=thread['start'], end=thread['end']),
                        adjust=bool(spec['change']))

        items = [item(p, self._th_spec(p)) for p in self.th_extra] + [item(self.th_pick, spec)]
        recipe = dict(type='thread', items=items)
        if self.th_real.isChecked():
            recipe['real'] = True
        existing = list(self.document.bodies)

        def build():
            return hist.offloaded(hist.run_thread, existing, recipe)

        def done(bodies):
            self.document.pending_op = recipe
            many = f' ×{len(items)}' if len(items) > 1 else ''
            self.document.pending_label, self.document.pending_icon = f'Gwint {th.label(thread)}{many}' + (' (prawdziwy)' if recipe.get('real') else ''), 'thread'
            self.document.commit(bodies)
            self.th_pick = None
            self.th_extra = []
            self.view.set_thread_preview(None)
            self.view.set_handles([])
            self.th_status.setText(f'Dodano gwint {th.label(thread)}. Kliknij kolejny otwór albo wałek.')

        self.run_operation(f'Gwint {th.label(thread)}', build, done)

    def convert_thread(self):
        """Gwint kosmetyczny wskazanego otworu / wałka zamieniony na taki sam, ale prawdziwy (zwoje w bryle) - w tle."""
        from . import threads as th
        if self.th_pick is None:
            return
        body = self.document.get(self.th_pick['id'])
        existing = th.threads_on(body.threads, self.th_pick['info']) if body is not None else []
        if not existing:
            self.toast('Ten otwór / wałek nie ma gwintu wirtualnego.')
            return
        thread = existing[0]
        recipe = dict(type='thread_real', id=body.id, thread=dict(origin=thread['origin'], axis=thread['axis'], start=thread['start'],
                                                                 end=thread['end'], d=thread['d']))
        existing_bodies = list(self.document.bodies)

        def done(bodies):
            self.document.pending_op = recipe
            self.document.pending_label, self.document.pending_icon = f'Gwint {th.label(thread)} → prawdziwy', 'thread'
            self.document.commit(bodies)
            self.th_pick = None
            self.th_extra = []
            self.view.set_thread_preview(None)
            self.view.set_handles([])
            self.th_status.setText(f'Gwint {th.label(thread)} zamieniony na prawdziwy.')

        self.run_operation(f'Prawdziwy gwint {th.label(thread)}', lambda: hist.offloaded(hist.run_thread_real, existing_bodies, recipe), done)

    PAT_COLORS = {'X': (.87, .30, .32, 1), 'Y': (.20, .64, .45, 1), 'Z': (.27, .54, .89, 1)}

    def _place_pattern_handles(self):
        """Szyk prostokątny: strzałki X, Y, Z na obiekcie - przeciągnięcie zmienia odstęp w tym kierunku (przez zero:
        kopie przechodzą na drugą stronę). Koniec strzałki stoi na pierwszej kopii."""
        body = self.document.get(self.pat_id) if self.pat_id else None
        if self.mode != 'pattern' or body is None or body.mesh is None or self.pat_kind.currentData() != 'rect':
            self.view.set_handles([])
            return
        center, size = self._pattern_center(body)
        base = max(float(np.max(size)) * .45, 4.0)
        axes = self._pattern_axes(body)
        handles = []
        for i, axis in enumerate('XYZ'):
            sign = next(b.sign for b in self.pat_dirs[i] if b.isChecked())
            direction = np.array(axes[axis], float) * sign
            gap = self.pat_gaps[i].value()
            count = int(round(self.pat_counts[i].value()))
            length = gap if count > 1 and gap > base * .5 else base       # krótka strzałka też daje się złapać
            handles.append(dict(id='pat' + axis, start=center, tip=center + direction * length, dir=direction,
                                color=self.PAT_COLORS[axis], label=f'{axis} {gap:g}' if count > 1 else axis))
        self.view.set_handles(handles)

    def _pattern_drag(self, axis, delta):
        i = 'XYZ'.index(axis)
        pair = self.pat_dirs[i]
        if self._hv is None or self._hv[0] != axis:
            sign = next(b.sign for b in pair if b.isChecked())
            self._hv = (axis, sign * self.pat_gaps[i].value(), sign)
        signed = self._hv[1] + delta * self._hv[2]           # odstęp ze znakiem wzdłuż osi
        if int(round(self.pat_counts[i].value())) < 2 and abs(signed) > 1e-6:
            self.pat_counts[i].setValue(2)                    # przeciągnięcie strzałki przy jednej kopii dodaje kopię
        new_sign = 1 if signed >= 0 else -1
        for b in pair:
            b.setChecked(b.sign == new_sign)
        self.pat_gaps[i].setValue(round(abs(signed), 1))
        self._timers['pattern'].start()

    def update_pattern_preview(self):
        """Podgląd na żywo: kopie siatki obiektu przekształcone macierzami (bez OCC), więc zmiana parametru jest natychmiastowa."""
        if self.mode != 'pattern':
            return
        body = self.document.get(self.pat_id) if self.pat_id else None
        self.view.sel_vertices = [np.array([s.value() for s in self.pat_pivot], float)] if body is not None and self.pat_kind.currentData() == 'circ' else []
        if self._hv is None:
            self._place_pattern_handles()
        if body is None or body.mesh is None or (self.pat_kind.currentData() == 'path' and self.pat_path is None):
            self.view.set_preview_mesh(None)
            return
        try:
            ops, moved = self._pattern_ops(body)
            mesh = kernel.pattern_mesh(body.mesh, ([moved] if moved else []) + ops, original=moved is None)
        except kernel.CadError as exc:
            self.view.set_preview_mesh(None)
            self.pat_status.setText(str(exc))
            return
        self.pat_status.setText(f'Kopie: {len(ops)} (razem z oryginałem {len(ops) + 1}).' if ops else 'Brak kopii - zwiększ ilość.')
        self.view.set_preview_mesh(mesh, color=(.3, .8, .5, .55), line_color=(.05, .4, .2, 1), width=2)

    def apply_pattern(self):
        if self.busy:
            return
        body = self.document.get(self.pat_id) if self.pat_id else None
        if body is None:
            self.toast('Kliknij bryłę lub szkic, który ma być powielony.')
            return
        try:
            ops, moved = self._pattern_ops(body)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        if not ops and moved is None:
            self.toast('Zwiększ ilość kopii.')
            return
        join = self.pat_join.isChecked() and body.kind == 'solid'
        kind = self.pat_kind.currentData()
        if kind == 'rect':
            axes = self._pattern_axes(body)
            params = dict(counts=[int(round(c.value())) for c in self.pat_counts], spacing=self._pattern_spacing(), axes=[list(axes[a]) for a in 'XYZ'])
        elif kind == 'circ':
            params = dict(axis=list(self._pattern_axes(body)[self.pat_axis.currentData()]), pivot=[s.value() for s in self.pat_pivot], count=int(round(self.pat_ccount.value())),
                          angle=self.pat_angle.value(), radius=self.pat_radius.value())
        else:
            params = dict(points=[[float(c) for c in q] for q in np.asarray(self.pat_path, float)], count=int(round(self.pat_lcount.value())),
                          fit=self.pat_fit.isChecked(), spacing=self.pat_lgap.value())
        recipe = dict(type='pattern', id=body.id, kind=kind, params=params, join=join, out=[uuid.uuid4().hex for _ in ops])
        if not join and self.pat_result.currentData() == 'group':
            recipe['group'] = uuid.uuid4().hex             # „jako jeden element”: oryginał i kopie w jednej grupie
        targets = self._multi_targets(body.id, ('solid', 'sketch'))
        if len(targets) > 1:          # kilka zaznaczonych: każdy powielony tak samo
            steps = []
            for i in targets:
                other = self.document.get(i)
                step = dict(recipe, id=i, join=join and other.kind == 'solid', out=[uuid.uuid4().hex for _ in ops])
                if kind == 'rect':
                    axes = self._pattern_axes(other)
                    step['params'] = dict(params, axes=[list(axes[a]) for a in 'XYZ'])
                if recipe.get('group'):
                    step['group'] = uuid.uuid4().hex
                steps.append(step)
            self.selected = []
            self._run_multi('Szyk', 'pattern', steps)
            return
        existing = list(self.document.bodies)

        def build():
            return list(hist.offloaded(hist.run_pattern, existing, recipe))

        def apply(new):
            self.document.pending_op = recipe
            self.document.commit(new)
            self.selected = []

        self.view.set_preview_mesh(None)
        self.run_operation('Szyk', build, apply, after=lambda: self.set_mode(None))

    # =====================================================================
    # przesuwanie i obracanie zaznaczonych szkiców / brył z uchwytami 3D
    # =====================================================================
    def pick_transform_target(self, x, y):
        bid = self.pick_object(x, y)
        body = self.document.get(bid) if bid else None
        if body is None:
            self.toast('Kliknij bryłę lub szkic.')
            return
        if self.t_target is not None and bid in (getattr(self, 't_group', None) or [self.t_target.id]):
            self.t_target=body;self._place_gizmo()
            return          # zachowaj parametry; uchwyt podąża za ostatnio klikniętym obiektem
        self.select_transform_target(body)

    def select_transform_target(self, body):
        self.override = {}
        self.t_target = body
        self.t_group = self._group_ids(body.id)
        if body.id in self.selected and len(self.selected) > 1:
            # kilka zaznaczonych (np. cała grupa z listy Obiekty): przesuwają się / obracają razem, wokół wspólnego środka
            for i in self.selected:
                for j in self._group_ids(i):
                    if j not in self.t_group and self.document.get(j) is not None:
                        self.t_group.append(j)
        members = [self.document.get(i) for i in self.t_group]
        if len(members) > 1:          # grupa: wspólna ramka i wspólny środek obrotu
            box = kernel.bounds(kernel.compound([m.shape for m in members]))
            self.t_mass = np.array(box.center.toTuple(), float)
        else:
            box = kernel.bounds(body.shape)
            self.t_mass = np.array(_center(body.shape).toTuple(), float)
        self.t_center = np.array(box.center.toTuple(), float)
        self.view.clear_body_matrices()
        self.t_radius = max(8.0, max(box.xlen, box.ylen, box.zlen) * .75)
        self.t_status.setText(f'Zaznaczono: {body.name}' + (f' (grupa: {len(members)})' if len(members) > 1 else ''))
        for spin in self.t_spins:
            spin.blockSignals(True)
            spin.setValue(0)
            spin.blockSignals(False)
        self.selected = list(self.t_group)
        self.view.free_drag = (body.id, self.t_center, set(self.t_group)) if self.mode == 'move' else None
        self.refresh()
        self._place_gizmo()

    def _place_gizmo(self):
        """Uchwyty w stylu Fusion 360: przesuwanie = kolorowe strzałki osi + kwadraty płaszczyzn; obrót = kolorowe pierścienie."""
        if self.t_target is None or self.mode not in ('move', 'rotate'):
            self.view.set_handles([])
            return
        c, r = self.t_center, self.t_radius
        if self.mode=='move' and self.t_target is not None and self.t_target.mesh is not None:c=np.asarray(self.t_target.mesh.center,float)
        axes = [np.array(a) for a in AXES]
        handles = []
        if self.mode == 'move':
            base = c + np.array([s.value() for s in self.t_spins])
            if self.view.free_drag is not None:          # chwytanie bryły tam, gdzie jest teraz widoczna
                self.view.free_drag = (self.t_target.id, base, set(getattr(self, 't_group', None) or [self.t_target.id]))
            length = max(r, float(self.view.opts['distance']) * .13)
            for i, a in enumerate(axes):
                handles.append(dict(id='xyz'[i], kind='axis', start=base, tip=base + a * length, dir=a, color=AXIS_COLORS[i], label='XYZ'[i], min_px=46))
            for i, j, k in ((0, 1, 2), (0, 2, 1), (1, 2, 0)):
                a, b = axes[i], axes[j]
                q0 = base + (a + b) * .2 * length
                quad = [q0, q0 + a * .26 * length, q0 + (a + b) * .26 * length, q0 + b * .26 * length]
                handles.append(dict(id='p' + 'xyz'[i] + 'xyz'[j], kind='plane', quad=quad, plane_origin=base, normal=axes[k], color=AXIS_COLORS[k]))
        else:
            for i, a in enumerate(axes):
                e1 = np.cross(a, (0, 0, 1.0) if abs(a[2]) < .9 else (1.0, 0, 0))
                e1 /= np.linalg.norm(e1)
                handles.append(dict(id='xyz'[i], kind='ring', ring=(c, a, r), tip=c + e1 * r, dir=np.cross(a, e1), color=AXIS_COLORS[i], label='XYZ'[i]))
        self.view.set_handles(handles)

    def handle_point_dragged(self, hid, vec):
        """Przeciąganie kwadratu płaszczyzny lub samej bryły (lewy przycisk): przesunięcie w płaszczyźnie."""
        if self.mode != 'move' or self.t_target is None:
            return
        if self._hv is None or self._hv[0] != 'pt':
            self._hv = ('pt', np.array([s.value() for s in self.t_spins], float))
        mask = {'pxy': (0, 1), 'pxz': (0, 2), 'pyz': (1, 2)}.get(hid, (0, 1, 2))
        values = self._hv[1].copy()
        for i in mask:
            values[i] += float(vec[i])
        for spin, value in zip(self.t_spins, values):
            spin.blockSignals(True)
            spin.setValue(round(float(value), 2))
            spin.blockSignals(False)
        self.update_transform_preview()
        self._place_gizmo()
    def _transform_changed(self):
        self.update_transform_preview()
        if self._hv is None:
            self._place_gizmo()

    def handle_dragged(self, hid, delta):
        if hid=='section':
            self.section_dragged(delta);return
        if hid == 'ex':
            if self._hv is None:
                self._hv = self.ex_value.value()
            self.ex_value.setValue(round(self._hv + delta, 1))
            self._stretch_extrude()
        elif hid == 'ex2':
            if self._hv is None:
                self._hv = self.ex_second.value()
            self.ex_second.setValue(max(0.0, round(self._hv + delta, 1)))
        elif hid == 'off' and self.off is not None:
            if self._hv is None:
                self._hv = self._off_signed()
            self._off_set_signed(self._hv + delta)
        elif hid == 'split':
            if self._hv is None:
                self._hv = self.sp_offset.value()
            self.sp_offset.setValue(round(self._hv + delta, 1))
        elif hid == 'shell':
            if self._hv is None:
                self._hv = self.sh_thick.value()
            self.sh_thick.setValue(max(.1, round(self._hv + delta, 1)))
        elif hid == 'mod':
            if self._hv is None:
                self._hv = self.mod_size.value()
            self.mod_size.setValue(max(.1, round(self._hv + delta, 1)))
        elif hid in ('patX', 'patY', 'patZ'):
            self._pattern_drag(hid[3], delta)
        elif hid in ('thS', 'thE', 'thD'):
            self._th_drag(hid, delta)
        elif hid in ('plyH', 'plyP'):
            self.ply_handle_dragged(hid, delta)
        elif hid in ('scA', 'scX', 'scY', 'scZ'):
            self.scale_handle_dragged(hid, delta)
        elif hid in ('x', 'y', 'z') and self.t_target is not None:
            index = 'xyz'.index(hid)
            if self._hv is None or self._hv[0] != hid:
                self._hv = (hid, self.t_spins[index].value())
            value = self._hv[1] + (delta if self.mode == 'move' else math.degrees(delta / max(self.t_radius, 1e-6)))
            self.t_spins[index].setValue(round(value, 1))

    def _stretch_extrude(self):
        """Natychmiastowa reakcja podglądu na przeciąganie strzałki (jednostronne wyciągnięcie jednego profilu)."""
        base = getattr(self, '_ex_mesh_value', 0.0)
        if len({p.get('cluster', id(p)) for p in self.ex_profiles}) != 1 or self.ex_dir.currentData() != 'one' or abs(base) < 1e-6:
            return
        if any(p.get('kind') == 'cyl' for p in self.ex_profiles):
            return          # pierścień walca nie skaluje się wzdłuż jednej normalnej - podgląd liczy się na nowo
        factor = self.ex_value.value() / base
        if factor > .02:
            src = self.ex_profiles[0]
            self.view.stretch_preview(src['center'], src['normal'], factor)

    def handle_released(self, hid):
        if hid=='section':
            self._section_drag_start=None;return
        self._hv = None
        if hid in ('ex', 'ex2'):
            self._place_extrude_handle()
        elif hid == 'off':
            self._off_place_handle()
        elif hid == 'mod':
            self._place_mod_handle()
        elif hid == 'split':
            self._place_split_handle()
        elif hid == 'shell':
            self._place_shell_handle()
        elif hid.startswith('pat'):
            self._place_pattern_handles()
        elif hid.startswith('th'):
            self._th_update()
        elif hid.startswith('ply'):
            self._ply_update()
        elif hid.startswith('sc'):
            self._sc_update()
        else:
            self._place_gizmo()

    def update_transform_preview(self):
        """Podgląd przesunięcia / obrotu bez liczenia geometrii: macierz nakładana na elementy GL (natychmiast, nawet dla dużych brył)."""
        if self.mode not in ('move', 'rotate') or self.t_target is None:
            return
        v = [s.value() for s in self.t_spins]
        m = QMatrix4x4()
        if self.mode == 'move':
            m.translate(*v)
        else:
            c = self.t_mass
            m.translate(*c)
            for axis, angle in ((2, v[2]), (1, v[1]), (0, v[0])):
                if angle:
                    m.rotate(float(angle), *[1.0 if i == axis else 0.0 for i in range(3)])
            m.translate(*(-c))
        self.view.set_body_matrices({identifier:m for identifier in (getattr(self,'t_group',None) or [self.t_target.id])})
    def apply_transform(self):
        if self.busy or self.t_target is None:
            self.toast('Kliknij obiekt, aby go zaznaczyć.')
            return
        self._timers['transform'].stop()
        v = tuple(s.value() for s in self.t_spins)
        target, mode = self.t_target, self.mode
        self.override = {}
        ids = [i for i in (getattr(self, 't_group', None) or [target.id]) if self.document.get(i) is not None] or [target.id]
        recipe = dict(type='transform', id=target.id, mode=mode, v=[float(c) for c in v])
        if len(ids) > 1:          # grupa przesuwa się / obraca razem, wokół wspólnego środka
            recipe.update(ids=ids, center=[float(c) for c in self.t_mass])
        existing = list(self.document.bodies)

        def build():
            return hist.offloaded(hist.run_transform, existing, recipe)

        def apply(bodies):
            self.view.clear_body_matrices()
            self.document.pending_op = recipe
            self.document.commit(bodies)
            self.selected = list(ids)

        self.view.set_handles([])
        self.run_operation('Przekształcenie', build, apply, after=lambda: self.set_mode(None))

    # =====================================================================
    # model, odświeżanie
    # =====================================================================
    def _history_limit_notice(self):
        """Ostrzeżenie przed limitem 999 kroków (raz na projekt) i informacja, gdy najstarsze kroki zaczynają wypadać."""
        doc = self.document
        seen = self.__dict__.setdefault('_limit_seen', {})
        state = seen.setdefault(id(doc), {'warned': False, 'dropped': 0})
        if doc.dropped > state['dropped']:
            if state['dropped'] == 0:
                self.toast(f'Historia osiągnęła limit {doc.MAX_UNDO} kroków - najstarsze kroki są usuwane. '
                           'Aby je zachować, zapisz wariant w menu historii przed dalszą pracą.', 12000)
            state['dropped'] = doc.dropped
        elif not state['warned'] and doc.history_length >= doc.WARN_UNDO:
            state['warned'] = True
            self.toast(f'Historia ma już {doc.history_length} kroków. Po {doc.MAX_UNDO} krokach najstarsze kroki będą usuwane - '
                       'jeśli chcesz je zachować, zapisz wariant w menu historii.', 12000)

    def _multi_targets(self, primary, kinds=('solid',), exclude=()):
        """Obiekty, na których wykona się operacja: wskazany, a gdy jest wśród kilku zaznaczonych (na liście obiektów
        albo na polu roboczym) - wszystkie zaznaczone odpowiedniego rodzaju (wskazany pierwszy)."""
        if primary is None:
            return []
        if primary not in self.selected or len(self.selected) < 2:
            return [primary]
        out = [primary]
        for i in self.selected:
            body = self.document.get(i)
            if i != primary and i not in exclude and body is not None and body.kind in kinds and i not in out:
                out.append(i)
        return out

    def _tint_targets(self, primary, kinds=('solid',), exclude=()):
        self.view.tints = {i: TINT_BASE for i in self._multi_targets(primary, kinds, exclude)}

    def _run_multi(self, label, icon, steps, select=None):
        """Ta sama operacja na kilku zaznaczonych obiektach - jeden krok historii (cofa się w całości)."""
        recipe = dict(type='multi', steps=steps)
        existing = list(self.document.bodies)

        def build():
            return list(hist.offloaded(hist.run_multi, existing, recipe))

        def apply(new):
            self.document.pending_op = recipe
            self.document.pending_label, self.document.pending_icon = label, icon
            self.document.commit(new)
            if select is not None:
                self._tool_select([i for i in select if self.document.get(i) is not None])

        self.view.set_preview_mesh(None)
        self.view.set_handles([])
        self.run_operation(f'{label} ×{len(steps)}', build, apply, after=lambda: self.set_mode(None))

    def _tool_select(self, ids, sketch=False):
        """Zaznaczenie ustawione przez program (wynik operacji, bryła wskazana w narzędziu). Bryła zaznacza się na stałe tylko
        kliknięciem użytkownika: po zamknięciu narzędzia takie zaznaczenie znika samo, o ile użytkownik go nie zmienił.
        Nowy szkic dostaje zaznaczenie na stałe (uchwyty do zmiany rozmiaru)."""
        ids = list(ids)
        if ids == self.selected:
            return
        self.selected = ids
        self._auto_selected = None if sketch else list(ids)

    def refresh(self, fit=False):
        self._history_limit_notice()
        auto = getattr(self, '_auto_selected', None)
        if auto is not None and self.mode is None:
            self._auto_selected = None
            if self.selected == auto:
                self.selected = []
        if getattr(self, '_quick_preview', False) and not self.busy:
            self._quick_preview = False                     # dokładny wynik (albo komunikat) zastępuje szybki podgląd kołnierza
            self.view.set_preview_mesh(None)
        if hasattr(self, '_warm_timer') and not self.busy:
            self._warm_timer.start()       # cofnij / ponów / otwarcie projektu: rozwinięcia blach przygotują się w tle
        live = {b.id for b in self.document.bodies}
        self.selected = [i for i in self.selected if i in live]
        self.edges = {i: es for i, es in self.edges.items() if i in live}
        bodies = [self.override.get(b.id, b) for b in self.document.bodies]
        if self.hist_ghost.isChecked():       # wygaszone szkice wracają do widoku
            bodies = [replace(b, visible=True) if (b.kind == 'sketch' and not b.visible) else b for b in bodies]
        revealed = getattr(self, 'revealed_ids', set())
        if revealed:        # szkic wygaszony po wyciągnięciu, pokazany okiem na liście
            bodies = [replace(b, visible=True) if (b.id in revealed and not b.visible) else b for b in bodies]
        if self.hidden_ids:
            bodies = [replace(b, visible=False) if b.id in self.hidden_ids else b for b in bodies]
        shown = {*self.selected, self._obj_hover} if self._obj_hover else set(self.selected)
        if shown:      # obiekt wskazany na liście jest widoczny i podświetlony, także gdy był ukryty albo wygaszony (np. szkic użyty w wyciągnięciu)
            bodies = [replace(b, visible=True) if (b.id in shown and not b.visible) else b for b in bodies]
        self.view.locked = frozenset(self.locked_ids)
        self.objects_update()
        self._hist_update()
        self._hist_compare_update()
        if self.document.deferred and not self.busy:
            self._replay_deferred()
        highlighted = [] if self.mode in ('sheet', 'flange', 'hem', 'tabwall') else self.selected
        if self._obj_hover and self.mode not in ('sheet', 'flange', 'hem', 'tabwall'):
            highlighted = [*highlighted, self._obj_hover]
        self.view.set_models(bodies, highlighted, self.edges)
        self.view.set_threads({b.id: b.threads for b in bodies if b.threads and b.visible})   # gwinty: lekkie linie, bez geometrii
        if getattr(self, 'th_pick', None) is not None:
            alive = {b.id for b in bodies if b.visible}
            if self.th_pick['id'] not in alive or any(x['id'] not in alive for x in self.th_extra):
                self.th_pick, self.th_extra = None, []   # walec z podglądem gwintu usunięty / ukryty: znika też podgląd
                if hasattr(self, 'th_status'):
                    self._th_update()
                else:
                    self.view.set_thread_preview(None)
        if fit:
            self.view.fit_all()
        if hasattr(self, '_refine_timer') and any(b.mesh is not None and not b.mesh.fine for b in self.document.bodies):
            self._refine_timer.start()     # duże bryły pokazane zgrubnie: dokładne siatki liczą się w tle
        self.undo_button.setEnabled(self.document.can_undo and not self.busy)
        self.redo_button.setEnabled(self.document.can_redo and not self.busy)
        name = self.document.path.name if self.document.path else 'Nowy projekt'
        self.setWindowTitle(f"{'● ' if self.document.dirty else ''}{name} — RCCAD")

    def _refine_meshes(self):
        """Dokładne siatki dla brył pokazanych zgrubnie - w tle (procesy liczące), bez blokowania okna i bez kroku historii.
        Gotowa siatka podmienia zgrubną, gdy bryła nadal jest w modelu; wcześniej policzone biorą się z pamięci od razu."""
        todo, changed = [], False
        for b in self.document.bodies:
            if b.mesh is None or b.mesh.fine or id(b.shape) in self._refining:
                continue
            ready = self.document.fine_mesh(b.shape)
            if ready is not None:
                changed = self.document.refined(b.shape, ready) or changed
            else:
                todo.append(b.shape)
        if changed:
            self.refresh()
        if not todo:
            return
        keys = {id(shape) for shape in todo}
        self._refining |= keys
        from . import workers

        def done(meshes):
            self._refining -= keys
            hit = False
            for shape, mesh in zip(todo, meshes or []):
                if mesh is not None:
                    hit = self.document.refined(shape, mesh) or hit
            if hit:
                self.refresh()

        def failed(_message):
            self._refining -= keys

        work = _Work(lambda: workers.fine_meshes(todo))
        work.signals.done.connect(done)
        work.signals.failed.connect(failed)
        self._refine_work = work
        self.pool.start(work)

    # ---------- historia ----------
    def _hist_values(self):
        """Wartości zmiennych projektu (nazwa -> liczba); błędne wyrażenia dają pusty słownik i komunikat."""
        try:
            return hist.variable_values(self.document.variables)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return {}

    def _hist_ctx(self):
        return hist.Context(self.document.constraints, self._hist_values())

    def _hist_edit_close(self):
        self.hist_edit.hide()
        self.cancel_previews()
        self.view.set_preview_mesh(None)

    def _hist_toggled(self, on):
        self.hist_bar.setVisible(on)
        self._hist_sig = None
        self._hist_update()
        self._layout_overlays()

    def _hist_compare_update(self):
        """Porównanie przed / po: bryły z poprzedniej wersji historii (sprzed ostatniej edycji) jako czerwona nakładka."""
        if self.mode is not None:
            return
        if not (self.hist_compare.isChecked() and self.document.backup):
            if getattr(self, '_compare_on', False):
                self._compare_on = False
                self.view.set_selection_meshes(None)
            return
        states, current, _ = self.document.backup
        meshes = [b.mesh for b in self.document.meshed([x for x in states[current][0] if x.kind == 'solid' and x.visible]) if b.mesh is not None]
        self._compare_on = bool(meshes)
        self.view.set_selection_meshes(meshes or None, color=(.9, .2, .2, .22), line_color=(.8, .1, .1, 1))

    def _hist_icon(self, key):
        cache = self.__dict__.setdefault('_hist_icons', {})
        if key not in cache:
            cache[key] = QIcon(ui.icons.pixmap('t_' + hist.ICONS.get(key, 'move'), 26))
        return cache[key]

    @staticmethod
    def _hist_chip_style(i, info, current):
        style = []
        if i > current:      # cofnięte kroki: przerywany obrys, można do nich wrócić
            style.append('border-style:dashed; border-color:#9fb2c4;')
        if info.get('group'):
            style.append('border-top:3px solid #187ac1;')
        if info.get('off'):      # krok wyłączony: wygaszony symbol
            style.append('background:#e6ecf2; border-style:dotted; border-color:#9fb2c4;')
        if info.get('stale'):
            style.append('border:2px solid #e5262b;')
        return 'QToolButton#padTool { ' + ' '.join(style) + ' }' if style else ''

    def _hist_update(self):
        """Pasek historii jest uaktualniany przyrostowo: nowy krok dodaje jeden symbol, skok w historii tylko zmienia obrysy
        (bez tworzenia widżetów), więc praca nad projektem nie zwalnia nawet przy setkach kroków."""
        if not self.hist_bar.isVisible():
            return
        infos, current = self.document.infos()
        if not self.document.can_redo:
            self._hist_trim = False
        if self._hist_trim:
            infos = infos[:current + 1]
        self.hist_revert.setEnabled(bool(self.document.backup))
        keyed = [(hist.step_label(i), i.get('icon'), bool(i.get('stale')), bool(i.get('off')), i.get('note'), i.get('group'), i.get('why')) for i in infos]
        mode = (tuple(sorted(self._hist_folded)), self._hist_filter)
        old = self._hist_sig
        if old is not None and old == (keyed, current, mode):
            return
        full = old is None or old[2] != mode or (old[1] != current and (self._hist_folded or self._hist_filter != 'Wszystkie kroki'))
        prefix = 0
        if not full:
            old_keyed = old[0]
            limit = min(len(old_keyed), len(keyed))
            while prefix < limit and old_keyed[prefix] == keyed[prefix]:
                prefix += 1
        self._hist_sig = (keyed, current, mode)
        widgets = self._hist_widgets
        if self._hist_stretch and self.hist_row.count():
            self.hist_row.takeAt(self.hist_row.count() - 1)
            self._hist_stretch = False
        for j in [j for j in widgets if j >= prefix]:
            for w in widgets.pop(j):
                self.hist_row.removeWidget(w)
                w.deleteLater()
        active = None
        for i in range(prefix, len(infos)):
            info = infos[i]
            group = info.get('group')
            folded = bool(group) and group in self._hist_folded and not (infos[current].get('group') == group)
            starts = bool(group) and (i == 0 or infos[i - 1].get('group') != group)
            if (folded and not starts) or (not folded and i != current and i != 0 and not hist.passes_filter(info, self._hist_filter)):
                continue
            made = []
            if group and (i == 0 or infos[i - 1].get('group') != group):
                size = sum(1 for x in infos[i:] if x.get('group') == group)
                tag = QPushButton(('▸ ' if folded else '▾ ') + group + (f' ({size})' if folded else ''))
                tag.setFlat(True)
                tag.setCursor(Qt.PointingHandCursor)
                tag.setToolTip('Kliknij, aby zwinąć / rozwinąć grupę kroków')
                tag.setStyleSheet('color:#187ac1; font-size:11px; font-weight:700; background:transparent; border:none; padding:0 4px;')
                tag.clicked.connect(lambda _=False, g=group: self._hist_fold(g))
                self.hist_row.addWidget(tag)
                made.append(tag)
            if folded:
                widgets[i] = made
                continue
            chip = _HistChip()
            chip.setObjectName('padTool')
            chip.setIcon(self._hist_icon(info.get('icon')))
            chip.setIconSize(QSize(26, 26))
            chip.setFixedSize(42, 38)
            chip.setCheckable(True)
            editable = bool(info.get('op')) or info.get('icon') == 'sketch'
            chip.setToolTip(f"{i}. {info.get('note') or hist.step_label(info)}" + (f"\n({hist.step_label(info)})" if info.get('note') else '') + (f"\nGrupa: {group}" if group else '') + (('\nBŁĄD: ' + info.get('why', 'nie dało się przeliczyć tego kroku')) if info.get('stale') else '')
                            + ('\nDwuklik: edytuj parametry' if editable else '') + ('\nKrok wyłączony (pomijany)' if info.get('off') else ''))
            chip.clicked.connect(lambda _=False, n=i: self.history_goto(n))
            chip.editRequested.connect(lambda n=i: self.history_edit(n))
            if i:
                chip.setContextMenuPolicy(Qt.CustomContextMenu)
                chip.customContextMenuRequested.connect(lambda pos, n=i, c=chip: self._history_menu(n, c.mapToGlobal(pos)))
            self.hist_row.addWidget(chip)
            made.append(chip)
            widgets[i] = made
        # obrysy i zaznaczenie wszystkich symboli (tanie: bez tworzenia widżetów, arkusz stylu ustawiany tylko przy zmianie)
        for i, made in widgets.items():
            chip = made[-1]
            if not isinstance(chip, _HistChip):
                continue
            chip.setChecked(i == current)
            sheet = self._hist_chip_style(i, infos[i], current)
            if chip.property('sheet') != sheet:
                chip.setProperty('sheet', sheet)
                chip.setStyleSheet(sheet)
            if i == current:
                active = chip
        self.hist_row.addStretch(1)
        self._hist_stretch = True
        if active is not None:
            QTimer.singleShot(0, lambda a=active: self.hist_scroll.ensureWidgetVisible(a, 40, 0) if a.parent() else None)

    def _history_menu(self, index, pos):
        from PySide6.QtWidgets import QMenu
        states = self.document.states()
        if not 0 < index < len(states) or self.busy:
            return
        menu = QMenu(self)
        edit = menu.addAction('Edytuj parametry…')
        off = menu.addAction('Włącz krok' if states[index][1].get('off') else 'Wyłącz krok')
        menu.addSeparator()
        left = menu.addAction('Przesuń wcześniej')
        right = menu.addAction('Przesuń później')
        left.setEnabled(index > 1)
        right.setEnabled(index < len(states) - 1)
        menu.addSeparator()
        note = menu.addAction('Nazwij krok…')
        group = menu.addAction('Grupa…')
        menu.addSeparator()
        delete = menu.addAction('Usuń krok')
        chosen = menu.exec(pos)
        if chosen is edit:
            self.history_edit(index)
        elif chosen is off:
            self.history_restructure(lambda st, c, job: hist.toggle_step(st, index, c, job))
        elif chosen is left:
            self.history_restructure(lambda st, c, job: hist.move_step(st, index - 1, c, job))
        elif chosen is right:
            self.history_restructure(lambda st, c, job: hist.move_step(st, index, c, job))
        elif chosen is note:
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(self, 'Nazwa kroku', 'Podpis kroku (puste = domyślny):', text=states[index][1].get('note', ''))
            if ok:
                self.document.set_info(index, note=text.strip()[:80])
                self.refresh()
        elif chosen is group:
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(self, 'Grupa kroków', 'Nazwa grupy (kolejne kroki o tej samej nazwie tworzą grupę; puste = bez grupy):', text=states[index][1].get('group', ''))
            if ok:
                self.document.set_info(index, group=text.strip()[:40])
                self.refresh()
        elif chosen is delete:
            self.history_restructure(lambda st, c, job: hist.delete_step(st, index, c, job))

    def history_restructure(self, change):
        """Wyłączenie / usunięcie / zmiana kolejności kroku: nowa oś czasu jest przeliczana w tle, poprzednią można przywrócić strzałką."""
        if self.busy:
            return
        states = self.document.states()
        if self.mode is not None:
            self.set_mode(None)

        def apply(result):
            new_states, failed = result
            self.document.rewrite(new_states, len(new_states) - 1)
            self.selected, self.edges = [], {}
            if failed:
                self.toast(f'{failed} kroków nie dało się przeliczyć (oznaczone na czerwono) - popraw je albo cofnij zmianę.', 7000)

        constraints = self._hist_ctx()
        self.run_history(lambda job: change(states, constraints, job), apply)

    def _replay_deferred(self):
        """Operacja wykonana po przeskoku w historii została wstawiona w środek: późniejsze kroki liczymy od nowa na jej wyniku (w tle)."""
        prev, future = self.document.deferred
        self.document.deferred = None
        current, steps, before = self.document.bodies, [], prev
        for bodies, info in future:
            steps.append((before, bodies, info))
            before = bodies

        def apply(result):
            tail, failed = result
            self.document.append_states(tail)
            self.selected, self.edges = [], {}
            self.toast(f'Wstawiono krok w środek historii, {failed} kroków wymaga poprawy (czerwone).' if failed else 'Wstawiono krok w środek historii, następne kroki przeliczone.', 4500)

        constraints = self._hist_ctx()
        self.run_history(lambda job: hist.rebuild(current, steps, constraints, job), apply)

    def _hist_fold(self, group):
        self._hist_folded ^= {group}
        self._hist_sig = None
        self._hist_update()

    def history_step(self, delta, absolute=False):
        """Skróty: Alt+←/→ krok wstecz / naprzód, Alt+Home / Alt+End początek / koniec historii."""
        if self.busy:
            return
        count, current = len(self.document.infos()[0]), self.document.infos()[1]
        self.history_goto(max(0, min(count - 1, delta if absolute else current + delta)))

    def history_menu(self):
        from PySide6.QtWidgets import QInputDialog, QMenu
        if self.busy:
            return
        menu = QMenu(self)
        save = menu.addAction('Zapisz bieżącą historię jako wariant…')
        names = list(self.document.snapshots)
        loaders, removers = {}, {}
        if names:
            menu.addSeparator()
        for name in names:
            sub = menu.addMenu('Wariant: ' + name)
            loaders[sub.addAction('Wczytaj (można cofnąć strzałką)')] = name
            removers[sub.addAction('Usuń wariant')] = name
        menu.addSeparator()
        filters = {}
        filter_menu = menu.addMenu('Filtr kroków: ' + self._hist_filter)
        for name in hist.FILTERS:
            act = filter_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(name == self._hist_filter)
            filters[act] = name
        export = menu.addAction('Eksportuj listę kroków do pliku tekstowego…')
        auto = self._autosave_path()
        recover = menu.addAction('Otwórz autozapis') if auto.exists() else None
        chosen = menu.exec(self.hist_menu_button.mapToGlobal(self.hist_menu_button.rect().topLeft()))
        if chosen is None:
            return
        if chosen is save:
            text, ok = QInputDialog.getText(self, 'Wariant', 'Nazwa wariantu:', text=f'Wariant {len(names) + 1}')
            if ok and text.strip():
                self.document.snapshot(text.strip()[:60])
                self.toast('Wariant zapisany w projekcie (pamiętaj o zapisie pliku).', 3500)
                self.refresh()
        elif chosen in loaders:
            self.set_mode(None) if self.mode is not None else None
            self.document.restore_snapshot(loaders[chosen])
            self.selected, self.edges = [], {}
            self.refresh()
        elif chosen in removers:
            self.document.delete_snapshot(removers[chosen])
            self.refresh()
        elif chosen in filters:
            self._hist_filter = filters[chosen]
            self._hist_sig = None
            self._hist_update()
        elif chosen is export:
            self.history_export_text()
        elif recover is not None and chosen is recover:
            def loaded(doc):
                self.toggle_section(False,cancel_tool=False)
                self.section_origin=self.section_normal=None
                self.document = doc
                self.selected = []
            self.run_operation('Otwieranie autozapisu', lambda: Document.load(auto), loaded, True)

    def history_export_text(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Eksportuj listę kroków', 'Historia.txt', 'Tekst (*.txt)')
        if not path:
            return
        infos, current = self.document.infos()
        lines = [f"Historia projektu{' - ' + self.document.path.stem if self.document.path else ''}", '']
        for i, info in enumerate(infos):
            line = f"{i:3d}. {info.get('note') or hist.step_label(info)}"
            if info.get('note'):
                line += f" ({hist.step_label(info)})"
            if info.get('group'):
                line += f" [{info['group']}]"
            if info.get('off'):
                line += ' (wyłączony)'
            if info.get('stale'):
                line += ' BŁĄD: ' + info.get('why', 'nie dało się przeliczyć')
            lines.append(line + ('   <- bieżący' if i == current else ''))
        if self.document.variables:
            lines += ['', 'Zmienne:', *[f'  {k} = {v}' for k, v in self.document.variables.items()]]
        try:
            Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
            self.toast('Lista kroków zapisana.', 2500)
        except OSError as exc:
            self.toast(f'Nie można zapisać pliku: {exc}')

    @staticmethod
    def _autosave_path_for(document):
        if document.path is not None:
            return document.path.with_name(document.path.stem + '.autosave.rccadx')
        return Path.home() / '.rccad' / 'autozapis.rccadx'

    def _autosave_path(self):
        return self._autosave_path_for(self.document)

    def _autosave(self):
        """Co kilka minut zapisuje kopię projektu obok pliku (albo w ~/.rccad) w tle; nie zmienia stanu „zapisany”."""
        # zapisywane są tylko zatwierdzone kroki, więc autozapis działa także przy włączonym narzędziu (np. Kołnierz) - nie w trakcie operacji
        if self.busy or not self.document.dirty or not self.document.can_undo and not self.document.can_redo:
            return
        document, path = self.document, self._autosave_path()
        revision = document._revision
        if getattr(self, '_autosaved', None) == (id(document), revision):
            return

        def work():
            path.parent.mkdir(parents=True, exist_ok=True)
            document.save(path, mark=False)
            return revision

        work_item = _Work(work)
        work_item.signals.done.connect(lambda value, d=id(document): setattr(self, '_autosaved', (d, value)))
        work_item.signals.failed.connect(lambda message: None)
        self.pool.start(work_item)

    def history_revert(self):
        if self.busy or not self.document.backup:
            return
        self.document.restore_backup()
        self.selected, self.edges = [], {}
        self.refresh()

    def history_edit(self, index):
        """Edycja parametrów kroku (wymiary szkicu albo wyciągnięcie / wycięcie) i przeliczenie wszystkich następnych kroków."""
        if self.busy:
            return
        states = self.document.states()
        if not 0 < index < len(states):
            return
        bodies, info = states[index]
        recipe = info.get('op')
        if self.hist_edit.isVisible():
            self._hist_edit_close()
        lay = self.hist_edit_layout
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        title = QLabel(f"Edycja kroku {index}: {info.get('note') or hist.step_label(info)}")
        title.setObjectName('ptitle')
        lay.addWidget(title)
        if info.get('why'):
            why = _label('Powód błędu: ' + info['why'], 'status')
            why.setStyleSheet('color:#c0262b; background:transparent;')
            lay.addWidget(why)
        if recipe and recipe.get('type') in hist.RUNNERS:
            fields = dict(kind='recipe', collect=self._recipe_form(recipe, lay))
        else:
            known = {x.id for x in states[index - 1][0]}
            new_bodies = [b for b in bodies if b.id not in known]
            if not new_bodies:
                self.toast('Ten krok nie dodaje obiektów ani nie ma przepisu - nie ma czego edytować.')
                return
            added = [b for b in new_bodies if b.kind == 'sketch' and b.meta and b.meta.get('tool') in sm.EDITABLE]
            edits, links, factors, target = [], [], [], (added[0] if added else None)
            if target is not None:
                labels = sm.LABELS.get(target.meta['tool'], ())
                drivers = [(b, i, f'{b.name}: {cap}') for b in bodies if b.kind == 'sketch' and b.meta and b.meta.get('tool') in sm.EDITABLE
                           for i, cap in enumerate(sm.LABELS.get(b.meta['tool'], ()))]
                for n, (caption, value) in enumerate(zip(labels, sm.values(target.meta))):
                    formula = next((c['expr'] for c in self.document.constraints if c['b'] == target.id and c['bi'] == n and 'expr' in c), None)
                    box = QLineEdit(formula or value)
                    lay.addWidget(_label(caption, 'psub'))
                    lay.addWidget(box)
                    edits.append(box)
                    link = QComboBox()       # więz: ten wymiar zawsze równy wymiarowi innego szkicu
                    link.addItem('Wymiar niezależny', None)
                    current = next((c for c in self.document.constraints if c['b'] == target.id and c['bi'] == n and 'a' in c), None)
                    for b, i, text in drivers:
                        if b.id == target.id and i == n:      # wymiar nie może zależeć od samego siebie
                            continue
                        link.addItem(('= (ten szkic) ' if b.id == target.id else '= ') + text, (b.id, i))
                        if current and current['a'] == b.id and current['ai'] == i:
                            link.setCurrentIndex(link.count() - 1)
                    factor = QLineEdit(f"{float(current.get('k', 1.0)):g}" if current else '1')
                    factor.setPlaceholderText('współczynnik ×')
                    factor.setToolTip('Wymiar = współczynnik × wymiar wskazany powyżej (np. 0,5 = połowa, 2 = podwójny)')
                    lay.addWidget(link)
                    lay.addWidget(factor)
                    links.append(link)
                    factors.append(factor)
            lay.addWidget(_label('Położenie dodanych obiektów: przesunięcie (mm) i obrót (°) względem stanu z tego kroku', 'psub'))
            place = []
            for caption in ('Przesuń X', 'Przesuń Y', 'Przesuń Z', 'Obrót wokół X', 'Obrót wokół Y', 'Obrót wokół Z'):
                spin = _spin(0.0, -1e6, 1e6, 3, 1)
                lay.addWidget(_label(caption, 'psub'))
                lay.addWidget(spin)
                place.append(spin)
            fields = dict(kind='sketch', target=target, edits=edits, links=links, factors=factors, place=place, added=[b.id for b in new_bodies])
        self._hist_fields = fields
        if recipe and recipe.get('type') in ('extrude', 'revolve', 'mod') and (info.get('stale') or recipe.get('type') == 'mod' or any(p.get('k') == 'face' for p in recipe.get('profiles', ()))):
            pick = QPushButton('Wskaż ponownie w modelu…')
            pick.setObjectName('chip')
            pick.setToolTip('Model wraca do stanu sprzed kroku - kliknij ścianę, krawędź lub narożnik, których ma dotyczyć krok')
            pick.clicked.connect(lambda _=False: self.history_repick(index, recipe))
            lay.addWidget(pick)
        row = QHBoxLayout()
        for text, cb in (('Zastosuj', lambda: self._history_edit_apply(index, fields)), ('Anuluj', self._hist_edit_close)):
            b = QPushButton(text)
            b.setObjectName('primary' if text == 'Zastosuj' else 'chip')
            b.clicked.connect(lambda _=False, f=cb: f())
            row.addWidget(b)
        lay.addLayout(row)
        self.hist_edit.adjustSize()
        self.hist_edit.move(max(10, (self.view.width() - self.hist_edit.width()) // 2), self.hist_bar.y() - self.hist_edit.height() - 10)
        self.hist_edit.show()
        self.hist_edit.raise_()
        self._hist_hook_preview(index, fields)

    def _recipe_form(self, recipe, lay):
        """Pola edycji parametrów kroku dla danego typu operacji; zwraca funkcję zbierającą nowy przepis."""
        def field(caption, widget):
            lay.addWidget(_label(caption, 'psub'))
            lay.addWidget(widget)
            return widget

        kind = recipe['type']
        vals = self._hist_values()
        if kind == 'extrude':
            op = ui.Segmented([('Nowa', 'new', 'new'), ('Połącz', 'join', 'join'), ('Wytnij', 'cut', 'cut'), ('Wspólna', 'intersect', 'intersect')], 28)
            op.setCurrentIndex(['new', 'join', 'cut', 'intersect'].index(recipe['mode']))
            direction = ui.Segmented([('Jedna strona', 'one', 'one'), ('Symetrycznie', 'symmetric', 'sym'), ('Dwie strony', 'two', 'two'), ('Oba końce', 'ends', 'ends')], 28)
            direction.setCurrentIndex(['one', 'symmetric', 'two', 'ends'].index(recipe.get('dir', 'one')))
            d1, d2 = _ExprBox(recipe['d1'], vals), _ExprBox(recipe.get('d2', 0), vals)
            for caption, widget in (('Operacja', op), ('Kierunek', direction), ('Odległość (mm)', d1), ('Druga strona (mm)', d2)):
                field(caption, widget)
            self._hist_fields_extrude = dict(d1=d1, d2=d2, op=op, dir=direction)
            return lambda: dict(recipe, mode=op.currentData(), dir=direction.currentData(), d1=d1.raw(), d2=d2.raw())
        if kind in ('sweep', 'loft'):
            op = ui.Segmented([('Nowa', 'new', 'new'), ('Połącz', 'join', 'join'), ('Wytnij', 'cut', 'cut'), ('Wspólna', 'intersect', 'intersect')], 28)
            op.setCurrentIndex(['new', 'join', 'cut', 'intersect'].index(recipe['mode']))
            field('Operacja', op)
            if kind == 'sweep':
                return lambda: dict(recipe, mode=op.currentData())
            ruled = ui.Segmented([('Gładko', 'smooth', 'lf_smooth'), ('Prosto', 'ruled', 'lf_ruled')], 28)
            ruled.setCurrentIndex(1 if recipe.get('ruled') else 0)
            field('Przejście między profilami', ruled)
            return lambda: dict(recipe, mode=op.currentData(), ruled=ruled.currentData() == 'ruled')
        if kind == 'shell':
            thick = _ExprBox(recipe['thickness'], vals)
            direction = ui.Segmented([('Do wewnątrz', 'in', 'sh_in'), ('Na zewnątrz', 'out', 'sh_out')], 28)
            direction.setCurrentIndex(0 if recipe.get('inward', True) else 1)
            field('Grubość ścianki (mm)', thick)
            field('Kierunek', direction)
            return lambda: dict(recipe, thickness=thick.raw(), inward=direction.currentData() == 'in')
        if kind == 'revolve':
            op = ui.Segmented([('Nowa', 'new', 'new'), ('Połącz', 'join', 'join'), ('Wytnij', 'cut', 'cut'), ('Wspólna', 'intersect', 'intersect')], 28)
            op.setCurrentIndex(['new', 'join', 'cut', 'intersect'].index(recipe['mode']))
            angle = _ExprBox(recipe.get('angle', 360), vals)
            axis_spec = recipe['axis']
            axis = ui.Segmented([('Pozioma', 'u', 'ax_u'), ('Pionowa', 'v', 'ax_v')] + ([('Wskazana', 'line', 'ax_line')] if axis_spec['k'] == 'line' else []), 28)
            axis.setCurrentIndex(['u', 'v', 'line'].index(axis_spec['k']))
            for caption, widget in (('Operacja', op), ('Oś obrotu', axis), ('Kąt obrotu (°)', angle)):
                field(caption, widget)
            return lambda: dict(recipe, mode=op.currentData(), axis=axis_spec if axis.currentData() == 'line' else dict(k=axis.currentData()), angle=angle.raw())
        if kind == 'text':
            q = recipe['params']
            text = QLineEdit(q['text'])
            font = QFontComboBox()
            font.setFontFilters(QFontComboBox.ScalableFonts)
            font.setCurrentFont(QFont(q['font']))
            size, angle = _spin(float(q['size']), .1, 1e4, 2, 1), _spin(float(q['angle']), -360, 360, 1, 5)
            bold, italic = QCheckBox('Pogrubienie'), QCheckBox('Pochylenie')
            bold.setChecked(bool(q['bold']))
            italic.setChecked(bool(q['italic']))
            field('Treść', text)
            field('Czcionka', font)
            field('Wysokość liter (mm)', size)
            field('Kąt (°)', angle)
            lay.addWidget(bold)
            lay.addWidget(italic)
            self._hist_text = dict(text=text, size=size)
            return lambda: dict(recipe, params=dict(q, text=text.text(), font=font.currentFont().family(), size=size.value(), angle=angle.value(),
                                                    bold=bold.isChecked(), italic=italic.isChecked()))
        if kind == 'sketchmeta':
            meta = recipe['meta']
            boxes = []
            for caption, value in zip(sm.LABELS.get(meta['tool'], ()), sm.values(meta)):
                boxes.append(field(caption, QLineEdit(value)))
            return lambda: dict(recipe, meta=sm.apply_values(meta, [float(b.text().replace(',', '.')) for b in boxes]))
        if kind == 'transform':
            spins = [_ExprBox(c, vals) for c in recipe['v']]
            for caption, spin in zip(('X' if recipe['mode'] == 'move' else 'Obrót wokół X (°)', 'Y' if recipe['mode'] == 'move' else 'Obrót wokół Y (°)',
                                      'Z' if recipe['mode'] == 'move' else 'Obrót wokół Z (°)'), spins):
                field(caption + (' (mm)' if recipe['mode'] == 'move' else ''), spin)
            self._hist_spins = spins
            return lambda: dict(recipe, v=[x.raw() for x in spins])
        if kind == 'mod':
            mk = ui.Segmented([('Zaokrąglij', 'fillet', 'fillet'), ('Fazuj', 'chamfer', 'chamfer')], 28)
            mk.setCurrentIndex(['fillet', 'chamfer'].index(recipe['kind']))
            size = _ExprBox(recipe['size'], vals)
            field('Operacja', mk)
            field('Promień / odległość (mm)', size)
            self._hist_spins = [size]
            return lambda: dict(recipe, kind=mk.currentData(), size=size.raw())
        if kind == 'mirror':
            keep, join = QCheckBox('Zachowaj oryginał'), QCheckBox('Połącz z oryginałem (bryły)')
            keep.setChecked(bool(recipe.get('keep')))
            join.setChecked(bool(recipe.get('join')))
            lay.addWidget(keep)
            lay.addWidget(join)
            return lambda: dict(recipe, keep=keep.isChecked(), join=join.isChecked())
        if kind == 'bool':
            op = ui.Segmented([('Suma', 'union', 'union'), ('Różnica', 'subtract', 'subtract'), ('Część wspólna', 'intersect', 'common')], 28)
            op.setCurrentIndex(['union', 'subtract', 'intersect'].index(recipe['op']))
            keep = QCheckBox('Zachowaj bryły-narzędzia')
            keep.setChecked(bool(recipe.get('keep')))
            field('Operacja', op)
            lay.addWidget(keep)
            return lambda: dict(recipe, op=op.currentData(), keep=keep.isChecked())
        if kind == 'pattern':
            p, sp = dict(recipe['params']), []
            if recipe['kind'] == 'rect':
                counts = [_spin(float(c), 1, 200, 0, 1) for c in p['counts']]
                gaps = [_ExprBox(c, vals) for c in p['spacing']]
                for axis, c, g in zip('XYZ', counts, gaps):
                    field(f'Ilość {axis}', c)
                    field(f'Odstęp {axis} (mm)', g)
                sp = counts + gaps
                params = lambda: dict(p, counts=[int(round(c.value())) for c in counts], spacing=[g.raw() for g in gaps])
            elif recipe['kind'] == 'circ':
                count, angle, radius = _spin(float(p['count']), 1, 400, 0, 1), _ExprBox(p['angle'], vals), _ExprBox(p['radius'], vals)
                pivot = [_spin(float(c), -1e6, 1e6, 2, 1) for c in p['pivot']]
                field('Ilość kopii', count)
                field('Kąt łączny (°)', angle)
                field('Odległość od środka (mm)', radius)
                for axis, c in zip('XYZ', pivot):
                    field(f'Środek {axis} (mm)', c)
                sp = [count, angle, radius, *pivot]
                params = lambda: dict(p, count=int(round(count.value())), angle=angle.raw(), radius=radius.raw(), pivot=[c.value() for c in pivot])
            else:
                count, spacing = _spin(float(p['count']), 1, 400, 0, 1), _ExprBox(p['spacing'], vals)
                fit = QCheckBox('Rozłóż równo na całej ścieżce')
                fit.setChecked(bool(p.get('fit', True)))
                field('Ilość kopii', count)
                lay.addWidget(fit)
                field('Odstęp (mm)', spacing)
                sp = [count, spacing]
                params = lambda: dict(p, count=int(round(count.value())), fit=fit.isChecked(), spacing=spacing.raw())
            join = QCheckBox('Połącz kopie w jedną bryłę')
            join.setChecked(bool(recipe.get('join')))
            lay.addWidget(join)
            self._hist_spins = sp
            return lambda: dict(recipe, params=params(), join=join.isChecked())
        raise kernel.CadError('Ten krok nie ma parametrów do edycji.')

    def _history_edit_apply(self, index, fields):
        states = self.document.states()
        bodies, info = states[index]
        constraints = list(self.document.constraints)
        values_now = self._hist_values()
        try:
            if fields['kind'] == 'recipe':
                recipe = fields['collect']()
                new_info = dict(info, op=recipe)

                def first():
                    return hist.run_recipe(states[index - 1][0], recipe, values_now)
            else:
                target, new_info = fields['target'], info
                shift = [x.value() for x in fields['place']]
                meta = shape = None
                if target is not None:
                    numbers, formulas = [], {}
                    for n, box in enumerate(fields['edits']):
                        text = box.text().strip()
                        try:
                            numbers.append(float(text.replace(',', '.')))
                        except ValueError:      # wyrażenie ze zmiennych projektu: wymiar zostaje z nim powiązany
                            numbers.append(hist.evaluate(text, values_now))
                            formulas[n] = text
                    meta = sm.apply_values(target.meta, numbers)
                    shape = self._meta_shape(target.plane, meta)
                    constraints = [c for c in constraints if c['b'] != target.id]
                    for n, text in formulas.items():
                        constraints.append(dict(b=target.id, bi=n, expr=text))
                    for n, link in enumerate(fields['links']):
                        if link.currentData() and n not in formulas:
                            try:
                                k = float(fields['factors'][n].text().strip().replace(',', '.') or '1')
                            except ValueError:
                                raise ValueError('Współczynnik więzu musi być liczbą (np. 0,5).')
                            constraints.append(dict(a=link.currentData()[0], ai=link.currentData()[1], b=target.id, bi=n, k=k))
                    if hist.constraint_cycle(constraints):
                        raise ValueError('Te więzy tworzą pętlę (wymiar zależałby sam od siebie).')

                def first():
                    result = tuple(replace(b, shape=shape, mesh=kernel.display_mesh(shape), meta=meta) if (target is not None and b.id == target.id) else b for b in bodies)
                    if any(abs(x) > 1e-12 for x in shift):
                        result = hist.place_bodies(result, fields['added'], shift[:3], shift[3:])
                    return result
        except (ValueError, kernel.CadError) as exc:
            self.toast(str(exc) or 'Wpisz poprawne liczby.')
            return
        self._hist_edit_close()

        def build(job):
            edited = first()
            patched = list(states)
            patched[index] = (bodies, new_info)
            return hist.recompute(patched, index, edited, hist.Context(constraints, values_now), job)

        def apply(result):
            new_states, failed = result
            self.document.rewrite(new_states, len(new_states) - 1, constraints)
            self.selected, self.edges = [], {}
            if failed:
                self.toast(f'{failed} kroków nie dało się przeliczyć (oznaczone na czerwono, powód w dymku) - popraw je albo cofnij edycję.', 7000)

        self.run_history(build, apply)

    # ---------- podgląd na żywo parametrów kroku, ponowne wskazanie elementu, zmienne projektu ----------
    def _hist_hook_preview(self, index, fields):
        if fields['kind'] != 'recipe':
            return
        timer = getattr(self, '_hist_preview_timer', None)
        if timer is None:
            timer = self._hist_preview_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(220)
        try:
            timer.timeout.disconnect()
        except Exception:
            pass
        timer.timeout.connect(lambda: self._hist_edit_preview(index, fields))
        poke = lambda *_: timer.start()
        for w in self.hist_edit.findChildren(QDoubleSpinBox):
            w.valueChanged.connect(poke)
        for w in self.hist_edit.findChildren(QLineEdit):
            w.textChanged.connect(poke)
        for w in self.hist_edit.findChildren(QCheckBox):
            w.toggled.connect(poke)
        for w in self.hist_edit.findChildren(ui.Segmented):
            w.currentIndexChanged.connect(poke)
        timer.start()

    def _hist_edit_preview(self, index, fields):
        if not self.hist_edit.isVisible() or self.busy:
            return
        try:
            recipe = fields['collect']()
        except Exception:
            return
        base, values = self.document.states()[index - 1][0], self._hist_values()

        def compute():          # przeliczenie kroku liczy proces roboczy, okno pokazuje wynik, gdy jest gotowy
            solids = hist.background(hist.history_preview, hist.light(base), recipe, values, PREVIEW_TOL)
            return _merge_meshes(solids) if solids else None

        def show(mesh, error):
            if not self.hist_edit.isVisible():
                return
            if error or mesh is None:
                self.view.set_preview_mesh(None)
                return
            self.view.set_preview_mesh(mesh, color=(.95, .55, .2, .32), line_color=(.55, .3, .05, 1), width=2)

        self.run_preview('histedit', compute, show)

    def history_repick(self, index, recipe):
        """Naprawa czerwonego kroku: model wraca do stanu sprzed kroku, a użytkownik wskazuje ponownie ścianę / krawędź / narożnik."""
        self._hist_edit_close()
        self.history_goto(index - 1)
        self._repick = dict(index=index, recipe=recipe)
        self.toast('Kliknij ścianę (wyciągnięcie) albo krawędź / narożnik (faza, zaokrąglenie) w modelu sprzed tego kroku. Esc - anuluj.', 7000)

    def _repick_click(self, x, y):
        info = self._repick
        recipe = info['recipe']
        bodies = self.document.bodies
        try:
            if recipe['type'] in ('extrude', 'revolve'):
                hit = self.view.pick_face(x, y)
                body = self.document.get(hit[0]) if hit else None
                if body is None or body.kind != 'solid':
                    self.toast('Kliknij płaską ścianę bryły.')
                    return
                face, normal = self.view.face_at(body,hit)
                src = dict(kind='face', id=body.id, face=face, normal=tuple(float(c) for c in normal), center=face.Center().toTuple(), hit=tuple(float(c) for c in hit[2]))
                new = dict(recipe, profiles=hist.describe_profiles([src], bodies))
            else:
                vertex = self.view.nearest_vertex(x, y)
                if vertex is not None:
                    body = self.document.get(vertex[0])
                    point = np.asarray(vertex[1], float)
                    new = dict(recipe, id=body.id, verts=[[float(c) for c in point]], vrefs=hist.vertex_refs(body.shape, [point]), edges=[])
                else:
                    edge = self.view.nearest_edge(x, y, True)
                    if edge is None:
                        self.toast('Kliknij krawędź lub narożnik bryły.')
                        return
                    body = self.document.get(edge[0])
                    new = dict(recipe, id=body.id, verts=[], vrefs=[], edges=hist.edge_refs(body.shape, [edge[1]]))
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        self._repick = None
        self._history_edit_apply(info['index'], dict(kind='recipe', collect=lambda: new))

    def history_variables(self):
        """Panel zmiennych projektu (nazwa = wyrażenie); zmiana przelicza całą historię."""
        panel = self.hist_vars
        lay = self.hist_vars_layout
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    w = item.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()
        title = QLabel('Zmienne projektu')
        title.setObjectName('ptitle')
        lay.addWidget(title)
        lay.addWidget(_label('Użyj nazwy w polach kroków (np. szerokość / 2). Późniejsze zmienne mogą korzystać z wcześniejszych.', 'psub'))
        self._var_rows = []
        rows = QVBoxLayout()
        lay.addLayout(rows)

        def add_row(name='', expr=''):
            row = QHBoxLayout()
            n, e = QLineEdit(name), QLineEdit(expr)
            n.setPlaceholderText('nazwa')
            e.setPlaceholderText('wartość lub wyrażenie')
            drop = QToolButton()
            drop.setText('✕')
            row.addWidget(n, 1)
            row.addWidget(e, 2)
            row.addWidget(drop)
            rows.addLayout(row)
            entry = (n, e)
            self._var_rows.append(entry)

            def remove():
                self._var_rows.remove(entry)
                for w in (n, e, drop):
                    w.hide()
                    w.deleteLater()
            drop.clicked.connect(remove)

        for name, expr in self.document.variables.items():
            add_row(name, expr)
        if not self.document.variables:
            add_row()
        more = QPushButton('Dodaj zmienną')
        more.setObjectName('chip')
        more.clicked.connect(lambda: (add_row(), panel.adjustSize()))
        lay.addWidget(more)
        row = QHBoxLayout()
        for text, cb in (('Zastosuj', self._history_variables_apply), ('Zamknij', panel.hide)):
            b = QPushButton(text)
            b.setObjectName('primary' if text == 'Zastosuj' else 'chip')
            b.clicked.connect(lambda _=False, f=cb: f())
            row.addWidget(b)
        lay.addLayout(row)
        panel.adjustSize()
        panel.move(max(10, (self.view.width() - panel.width()) // 2), max(10, self.hist_bar.y() - panel.height() - 10))
        panel.show()
        panel.raise_()

    def _history_variables_apply(self):
        variables = {}
        for n, e in self._var_rows:
            name, expr = n.text().strip(), e.text().strip()
            if not name and not expr:
                continue
            if not name.isidentifier() or name in hist._FUNCTIONS or name == 'pi':
                self.toast(f'Nazwa zmiennej „{name}” jest nieprawidłowa (litery, cyfry i _; bez spacji, nie zaczyna się od cyfry).')
                return
            if name in variables:
                self.toast(f'Zmienna „{name}” jest zdefiniowana dwa razy.')
                return
            variables[name] = expr
        try:
            values = hist.variable_values(variables)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        if self.busy:
            return
        self.hist_vars.hide()
        states, constraints = self.document.states(), list(self.document.constraints)

        def apply(result):
            new_states, failed = result
            self.document.rewrite(new_states, len(new_states) - 1, constraints, variables)
            self.selected, self.edges = [], {}
            self.toast(f'Zmienne zastosowane, {failed} kroków wymaga poprawy.' if failed else 'Zmienne zastosowane, historia przeliczona.', 4000)

        self.run_history(lambda job: hist.recompute_all(states, hist.Context(constraints, values), job), apply)

    def run_history(self, build, apply):
        """Przeliczanie historii w tle z paskiem postępu; Esc przerywa (model zostaje bez zmian)."""
        job = {'cancel': False, 'i': 0, 'n': 0}
        self._hist_job = job

        def done(value):
            self._hist_job = None
            self.hist_status.setText('')
            apply(value)

        def work():
            value = build(job)
            try:        # siatki stanu, który zostanie pokazany - w tle i równolegle (procesy liczące), nie w oknie
                states = value[0]
                if states:
                    self.document.meshed(states[-1][0])
            except Exception:
                pass
            return value

        self._hist_tick.start()
        self.toast('Przeliczanie historii… (Esc przerywa)', 2500)
        self.run_operation('Przeliczanie historii', work, done)

    def _hist_progress(self):
        job = self._hist_job
        if job is None or not self.busy:
            self._hist_tick.stop()
            self._hist_job = None
            self.hist_status.setText('')
            return
        self.hist_status.setText(f"Przeliczanie {job['i'] + 1}/{job['n']} · Esc przerywa" if job['n'] else 'Przeliczanie…')

    def history_goto(self, index):
        if self.busy:
            return
        if self.mode is not None:
            self.set_mode(None)
        self.document.goto(index)
        self._hist_trim = False      # przeskok przez pasek historii zostawia kolejne kroki widoczne (przerywany obrys)
        self.selected, self.edges = [], {}
        self.refresh()

    def run_operation(self, label, function, apply, fit=False, after=None):
        if self.busy:
            return
        self.busy = True
        work = _Work(function)
        self._work = work
        state = dict(cancelled=False)

        def finish():
            self.busy = False
            self._work = None
            self._cancel_op = None

        def cancel():
            # Esc: wynik tej operacji zostanie pominięty, okno od razu wraca do pracy (proces dokończy liczenie w tle)
            state['cancelled'] = True
            finish()
            self.toast('Anulowano - model pozostał bez zmian.', 3000)
            self.refresh()

        self._cancel_op = cancel

        def done(value):
            if state['cancelled']:
                return
            try:
                self.document.pending_label = label
                self.document.pending_icon = hist.LABEL_ICONS.get(label)
                apply(value)
            except Exception as exc:
                self.toast(str(exc))
            finally:
                self.document.pending_label = self.document.pending_icon = self.document.pending_op = None
                finish()
                self.refresh(fit)
                if after:
                    after()
                self._warm_timer.start()       # po zmianie modelu rozwinięcia blach przygotowują się w tle

        def failed(message):
            if state['cancelled']:
                return
            finish()
            self.toast(message + ' Dotychczasowy model pozostał bez zmian.', 7000)
            self.refresh()

        work.signals.done.connect(done)
        work.signals.failed.connect(failed)
        self.pool.start(work)

    def _warm_sheets(self):
        """Rozwinięcia blach liczone w tle, gdy nic się nie dzieje - kliknięcie Rozłóż / Zegnij jest potem prawie natychmiastowe."""
        if self.busy:
            self._warm_timer.start()
            return
        for body in self.document.bodies:
            meta = (body.meta or {}).get('sheet') if body.kind == 'solid' else None
            recipe = meta.get('recipe') if meta else None
            if not recipe or not (recipe.get('flanges')):
                continue
            try:
                key = she._layout_key(recipe)
            except Exception:
                continue
            if key in self._warming or she.is_warm(recipe):
                continue
            from . import workers
            if workers.ready():
                # rozwinięcie przygotowuje proces rozwinięć tej blachy (ten sam, który potem rozkłada) - okno się nie zacina
                if workers.prepare(('layout', key), ('layout', body.id), hist.sheet_warm, recipe):
                    self._warming.add(key)
                    continue
            self._warming.add(key)
            work = _Work(lambda r=recipe: she.warm(r))
            work.signals.done.connect(lambda _=None, k=key: self._warming.discard(k))
            work.signals.failed.connect(lambda _=None, k=key: self._warming.discard(k))
            self.warm_pool.start(work, -1)

    # ---------- podglądy liczone w tle (GUI nigdy nie czeka na OpenCascade) ----------
    def working(self):
        """Czy coś liczy się w tle: operacja, podgląd, dopracowanie siatek albo przygotowanie w procesach."""
        from . import workers
        return (self.busy or any(st.get('running') for st in self._pv.values()) or bool(self._refining)
                or workers.pending() or getattr(self, '_exports', 0) > 0)

    def run_preview(self, key, compute, show):
        """Ostatnie żądanie wygrywa: przy szybkim przeciąganiu pośrednie wyniki są pomijane, a interfejs nie zamarza."""
        st = self._pv.setdefault(key, dict(running=False, pending=None, gen=0))
        st['gen'] += 1
        st['pending'] = (st['gen'], compute, show)
        if not st['running']:
            self._pv_next(key)

    def _pv_next(self, key):
        st = self._pv[key]
        if st['pending'] is None:
            st['running'] = False
            return
        gen, compute, show = st['pending']
        st['pending'] = None
        st['running'] = True
        work = _Work(compute)
        st['work'] = work
        work.signals.done.connect(lambda value, g=gen: self._pv_done(key, g, show, value, None))
        work.signals.failed.connect(lambda message, g=gen: self._pv_done(key, g, show, None, message))
        self.pool.start(work)

    def _pv_done(self, key, gen, show, value, error):
        st = self._pv[key]
        st['running'] = False
        if st['gen'] == gen:
            try:
                show(value, error)
            except Exception:
                pass
        self._pv_next(key)

    def cancel_previews(self):
        for st in self._pv.values():
            st['gen'] += 1
            st['pending'] = None

    def add_prepared(self, body):
        self.document.commit((*self.document.bodies, body))
        if self.mode != 'sketch':
            self._tool_select([body.id], sketch=body.kind == 'sketch')

    def clear_all(self):
        if self.busy:
            return
        if not self.document.bodies:
            self.toast('Pole robocze jest już puste.')
            return
        answer = QMessageBox.question(self, 'Wyczyścić pole', 'Na pewno wyczyścić całe pole?\nWszystkie bryły, szkice i cała historia zostaną usunięte - tego nie można cofnąć.',
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.set_mode(None)
        self.document.clear_all()
        self.selected = []
        self.hidden_ids, self.locked_ids, self._obj_doc = set(), set(), None
        self.revealed_ids = set()
        self.edges = {}
        self.override = {}
        self._repick = None
        self._hist_edit_close()
        self.hist_vars.hide()
        self._hist_sig = None
        self.view.clear_body_matrices()
        self.refresh()

    def undo(self):
        if not self.busy:
            self.document.undo()
            self._hist_trim = True
            self.edges = {}
            self.refresh()

    def redo(self):
        if not self.busy:
            self.document.redo()
            self.edges = {}
            self.refresh()

    # ---------- panel Obiekty ----------
    def _objects_numbers(self):
        """Numer porządkowy = kolejność dodania do projektu (osobno w grupie); numer pozostaje przy obiekcie po cofnięciu i ponowieniu."""
        if self._obj_doc is not self.document:
            self._obj_doc, self._obj_no, self._obj_count = self.document, {}, {}
            try:
                seq = [bodies for bodies, _ in self.document.states()]
            except Exception:
                seq = []
            seq.append(self.document.bodies)
        else:
            seq = [self.document.bodies]
        for bodies in seq:
            for b in bodies:
                if b.id not in self._obj_no:
                    cat = category(b)
                    self._obj_count[cat] = self._obj_count.get(cat, 0) + 1
                    self._obj_no[b.id] = self._obj_count[cat]
        return self._obj_no

    def objects_update(self):
        numbers = self._objects_numbers()
        items = [(b.id, category(b), numbers[b.id], b.name, b.group, b.folder) for b in self.document.bodies]
        self.objects.update_items(items, self.selected, self.shown_hidden(), self.locked_ids)

    def _objects_ready(self):
        if self.busy or self.mode is not None:
            self.toast('Zakończ bieżące narzędzie, aby zmienić listę obiektów.')
            return False
        return True

    def objects_hover(self, oid):
        if oid == self._obj_hover or self.busy:
            return
        self._obj_hover = oid if (oid and self.document.get(oid) is not None) else ''
        self.refresh()

    def objects_select(self, oid, modifiers):
        """Klik w wiersz podświetla obiekt na polu roboczym (także ukryty, wyłączony albo wygaszony); ponowny klik go odznacza."""
        if self.busy or self.document.get(oid) is None:
            return
        if self.mode is not None:
            self.set_mode(None)
        members = self._group_ids(oid)
        if modifiers & (Qt.ShiftModifier | Qt.ControlModifier):
            self.selected = [i for i in self.selected if i not in members] if oid in self.selected else [*self.selected, *[i for i in members if i not in self.selected]]
        elif sorted(self.selected) == sorted(members):
            self.selected = []
        else:
            self.selected = members
        self.refresh()

    def shown_hidden(self):
        """Obiekty ukryte (przekreślone oko na liście): ukryte okiem oraz szkice wygaszone po wyciągnięciu, których
        nie pokazano z powrotem. Szkic po wyciągnięciu jest więc zwyczajnie ukryty - kliknięcie oka go pokazuje."""
        revealed = getattr(self, 'revealed_ids', set())
        return {b.id for b in self.document.bodies if b.id in self.hidden_ids or (not b.visible and b.id not in revealed)}

    def _set_hidden(self, ids, hide):
        revealed = self.__dict__.setdefault('revealed_ids', set())
        ids = [i for i in ids if self.document.get(i) is not None]
        if hide:
            self.hidden_ids.update(ids)
            revealed.difference_update(ids)
            self.selected = [i for i in self.selected if i not in ids]
        else:
            self.hidden_ids.difference_update(ids)
            revealed.update(i for i in ids if not self.document.get(i).visible)

    def objects_hide(self, oid):
        """Oko na liście: klikniętą pozycję (szyk „jako jeden element” to jedna pozycja); gdy jest wśród zaznaczonych -
        wszystkie zaznaczone naraz (wszystkie dostają stan klikniętej)."""
        members = self._folder_targets([oid]) or self._group_ids(oid)
        self._set_hidden(members, oid not in self.shown_hidden())
        self.refresh()

    def objects_lock(self, oid):
        members = self._folder_targets([oid]) or self._group_ids(oid)     # kłódka: też wszystkie zaznaczone
        if oid in self.locked_ids:
            self.locked_ids.difference_update(members)
        else:
            self.locked_ids.update(members)
            self.selected = [i for i in self.selected if i not in members]
        self.refresh()

    # ---------- grupy (foldery) na liście obiektów ----------
    def _folder_targets(self, ids):
        """Elementy, których dotyczy polecenie grupy: kliknięta pozycja (z całym szykiem „jako jeden element”);
        gdy jest wśród zaznaczonych - wszystkie zaznaczone. Bez pozycji - zaznaczone."""
        ids = list(ids or [])
        if not ids or any(i in self.selected for i in ids):
            ids = [*ids, *self.selected]
        out = []
        for i in ids:
            for m in self._group_ids(i):
                if m not in out and self.document.get(m) is not None:
                    out.append(m)
        return out

    def objects_folder_move(self, ids, folder):
        if not self._objects_ready():
            return
        targets = self._folder_targets(ids)          # wśród zaznaczonych - wszystkie zaznaczone (także „Wyjmij z grupy”)
        if not targets:
            return
        self._set_folder(targets, folder, f'Do grupy: {folder}' if folder else 'Wyjęcie z grupy')

    def objects_folder_new(self, ids):
        if not self._objects_ready():
            return
        targets = self._folder_targets(ids)
        if not targets:
            self.toast('Zaznacz na liście elementy, które mają trafić do nowej grupy (Shift / Ctrl + klik).', 4000)
            return
        names = {b.folder for b in self.document.bodies}
        n = 1
        while f'Grupa {n}' in names:
            n += 1
        self._set_folder(targets, f'Grupa {n}', f'Nowa grupa: Grupa {n}')

    def objects_folder_rename(self, old, new):
        new = new.strip()[:60]
        if not new or new == old or not self._objects_ready():
            return
        ids = [b.id for b in self.document.bodies if b.folder == old]
        if ids:
            self._set_folder(ids, new, f'Zmiana nazwy grupy: {old} → {new}')

    def _set_folder(self, ids, folder, label):
        """Przeniesienie do grupy to krok historii (cofanie / ponawianie jak przy zmianie nazwy)."""
        ids = set(ids)
        if all(self.document.get(i).folder == folder for i in ids):
            return
        self.document.pending_op = dict(type='folder', ids=sorted(ids), folder=folder)
        self.document.pending_label, self.document.pending_icon = label, 'layers'
        self.document.commit([replace(b, folder=folder) if b.id in ids else b for b in self.document.bodies])
        self.refresh()

    def objects_folder_hide(self, ids):
        hidden = self.shown_hidden()
        self._set_hidden(ids, not all(i in hidden for i in ids))
        self.refresh()

    def objects_folder_delete(self, ids):
        if not self._objects_ready():
            return
        ids = [i for i in ids if self.document.get(i) is not None]
        if ids:
            self.selected = ids
            self.delete_selected()

    def objects_folder_select(self, ids):
        if self.busy:
            return
        if self.mode is not None:
            self.set_mode(None)
        ids = [i for i in ids if self.document.get(i) is not None]
        self.selected = [] if sorted(self.selected) == sorted(ids) else ids
        self.refresh()

    def objects_group_hide(self, cat):
        ids = [b.id for b in self.document.bodies if category(b) == cat]
        hidden = self.shown_hidden()
        self._set_hidden(ids, not all(i in hidden for i in ids))
        self.refresh()

    def objects_group_delete(self, cat):
        if not self._objects_ready():
            return
        ids = [b.id for b in self.document.bodies if category(b) == cat]
        if ids:
            self.selected = ids
            self.delete_selected()

    def objects_rename(self, oid, name):
        """Zmiana nazwy z listy to normalny krok historii (cofanie, ponawianie i przeliczanie od nowa działają jak przy innych operacjach)."""
        body = self.document.get(oid)
        name = name.strip()
        if body is None or not name or name == body.name or not self._objects_ready():
            return
        self.document.pending_op = dict(type='rename', id=oid, name=name)
        self.document.pending_label, self.document.pending_icon = f'Zmiana nazwy: {body.name} → {name}', 'text'
        self.document.commit([replace(b, name=name) if b.id == oid else b for b in self.document.bodies])
        self.refresh()

    def objects_delete(self, oid):
        """Kosz na liście: kliknięta pozycja, a gdy jest wśród zaznaczonych - wszystkie zaznaczone."""
        if self.busy:
            return
        targets = self._folder_targets([oid]) or self._group_ids(oid)
        if self.mode is not None:
            self.set_mode(None)
        self.selected = targets
        self.delete_selected()

    def delete_selected(self):
        if not self.busy and self.selected and self.mode is None:
            self.document.pending_op = dict(type='delete', ids=list(self.selected))
            self.document.commit([b for b in self.document.bodies if b.id not in self.selected])
            self.selected = []
            self.refresh()

    def copy_selected(self):
        self.clipboard = [(b.name, b.shape, b.kind, b.plane) for b in self.document.bodies if b.id in self.selected]
        if self.clipboard:
            self.toast('Skopiowano zaznaczone obiekty.', 2500)

    def cut_selected(self):
        if self.selected and self.mode is None and not self.busy:
            self.copy_selected()
            self.delete_selected()

    def paste_clipboard(self):
        if self.busy or not self.clipboard or self.mode is not None:
            return
        items = list(self.clipboard)

        def build():
            return [Body(n + ' — kopia', kernel.transform(sh, (10, 10, 0)), k, p).prepared() for n, sh, k, p in items]

        def apply(new):
            self.document.commit((*self.document.bodies, *new))
            self._tool_select([b.id for b in new])

        self.run_operation('Wklejanie', build, apply)

    def end_current_shape(self):
        """Prawy przycisk / Esc w trakcie rysowania: linia zostaje (jeśli ma ≥ 2 punkty) i rysowanie linii się kończy; inne kształty są porzucane."""
        if self.tool == 'line' and len(self.points) >= 2:
            self.finish_line()
            return
        self.points = []
        self.tangent_lines = []
        self.dim.hide()
        self.dim_panel.hide()
        self.view.set_preview_mesh(None)
        self.view.set_marker(None)
        self.show_sketch_hint()

    def sketch_hover_wanted(self):
        """Kursor ze znacznikiem i przyciąganiem (z opóźnieniem) działa od razu po wybraniu kształtu, także przed pierwszym kliknięciem,
        więc widać, gdzie kształt się zacznie. Okrąg styczny do dwóch linii najpierw wskazuje linie - kursor włącza się po ich wyborze."""
        if self.tool in (None, 'text'):
            return False
        if self.tool == 'circleTangent2':
            return len(self.tangent_lines) == 2
        return True

    def context_menu(self, x, y):
        if self.busy:
            return
        if self.section_picking:
            self.section_cancel_pick();return
        if self._lib_action is not None:          # prawy przycisk anuluje wskazywanie dla biblioteki
            self.library_cancel()
            return
        if self.mode in MEASURE_MODES:
            self._measure_back();return
        if self.mode == 'sketch':
            if self.points or self.tangent_lines:
                self.end_current_shape()
            return
        if self.mode in ('ply_wall','ply_between'):
            self.ply_right_click(x,y)
            return
        if self.mode == 'ply_cut':
            self.ply_cut_unpick(x, y)          # Do cięcia: prawy przycisk odznacza płytę
            return
        if self.mode is not None:
            return
        bid = self.pick_object(x, y)
        if bid and bid not in self.selected:
            self.selected = [bid]
            self.refresh()
        has = bool(self.selected)
        items = [('Kopiuj', 'Ctrl+C', self.copy_selected, has), ('Wytnij', 'Ctrl+X', self.cut_selected, has),
                 ('Wklej', 'Ctrl+V', self.paste_clipboard, bool(self.clipboard)), ('Usuń', 'Del', self.delete_selected, has)]
        menu = ui.PopupMenu(self, items, min_width=170)
        self._popup = menu
        menu.popup_at(QCursor.pos())

    # =====================================================================
    # plik
    # =====================================================================
    def file_menu(self):
        px = lambda kind: ui.icons.pixmap(kind, 34)
        entries = [(px('f_new'), 'Nowy projekt', 'Czysta przestrzeń robocza  ·  Ctrl+N', self.new_project),
                   (px('f_open'), 'Otwórz projekt…', 'Plik .rccadx  ·  Ctrl+O', self.open_project),
                   None,
                   (px('f_save'), 'Zapisz projekt', 'Zapis w bieżącym pliku  ·  Ctrl+S', self.save_project),
                   (px('f_saveas'), 'Zapisz jako…', 'Zapis pod nową nazwą', lambda: self.save_project(True)),
                   (px('f_saveas'), 'Zapisz kompaktowo…', 'Mniejszy plik: część historii odtwarzana z przepisów przy otwieraniu', lambda: self.save_project(True, compact=True)),
                   None,
                   (px('f_import'), 'Importuj…', 'STEP · STL · BREP · DXF · SVG', self.import_model),
                   (px('f_export'), 'Eksportuj…', 'STEP · STL · BREP · DXF', self.export_model),
                   None,
                   (px('f_help'), 'Pomoc', 'Samouczek: jak korzystać z programu', self.show_help),
                   None,
                   (px('f_about'), 'O programie', 'Wersja, data utworzenia i twórca', self.show_about)]
        menu = ui.RichMenu(self, entries, 'Plik', 330)
        self._popup = menu
        button = self.tools['file']
        menu.popup_at(button.mapToGlobal(QPoint(0, button.height() + 10)))

    def show_about(self):
        from .about import AboutDialog
        AboutDialog(self).exec()

    def show_help(self):
        from .help import HelpDialog
        HelpDialog(self).exec()

    def confirm_discard(self):
        if self.busy:
            self.toast('Trwa operacja — poczekaj na jej zakończenie.')
            return False
        if not self.document.dirty:
            return True
        return QMessageBox.question(self, 'Niezapisane zmiany', 'Odrzucić niezapisane zmiany?', QMessageBox.Discard | QMessageBox.Cancel,
                                    QMessageBox.Cancel) == QMessageBox.Discard

    def new_project(self):
        if self.confirm_discard():
            self.toggle_section(False,cancel_tool=False)
            self.section_origin=self.section_normal=None
            self.set_mode(None)
            self.document = Document()
            self.selected = []
            self.hidden_ids, self.locked_ids = set(), set()
            self.revealed_ids = set()
            self.refresh(True)

    def open_project(self):
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Otwórz projekt', '', 'RCCAD (*.rccadx)')
        if path:
            self.set_mode(None)

            def loaded(doc):
                self.toggle_section(False,cancel_tool=False)
                self.section_origin=self.section_normal=None
                self.document = doc
                self.selected = []
                self.hidden_ids, self.locked_ids = set(), set()
                self.revealed_ids = set()
            self.revealed_ids = set()

            self.run_operation('Otwieranie projektu', lambda: Document.load(path), loaded, True)

    def save_project(self, save_as=False, compact=False):
        """compact: zapis kompaktowy - pełna geometria tylko co kilka kroków historii (oraz bieżący krok); pozostałe kroki
        program odtwarza z ich przepisów przy otwieraniu projektu. Plik jest kilka razy mniejszy, otwieranie trwa dłużej."""
        path = self.document.path
        if save_as is True or path is None:
            title = 'Zapisz projekt kompaktowo' if compact else 'Zapisz projekt'
            value, _ = QFileDialog.getSaveFileName(self, title, str(path or 'Projekt.rccadx'), 'RCCAD (*.rccadx)')
            if not value:
                return
            path = Path(value)
            if path.suffix.lower() != '.rccadx':
                path = path.with_suffix('.rccadx')
        done = 'Projekt zapisany kompaktowo (otwieranie potrwa dłużej - kroki historii są odtwarzane).' if compact else 'Projekt zapisany.'
        self.run_operation('Zapisywanie projektu', lambda: self.document.save(path, compact=compact),
                           lambda _: (self._autosave_path_for(self.document).unlink(missing_ok=True), self.toast(done, 3500)))

    def import_model(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Importuj', '', 'Modele CAD i SVG (*.step *.stp *.brep *.brp *.stl *.dxf *.svg)')
        if not path:
            return
        if path.lower().endswith('.svg'):
            def build_svg():
                wires = kernel.svg_profiles(path, 'XY')
                folder = Path(path).stem[:60] if len(wires) > 1 else ''      # wiele konturów - razem w grupie na liście obiektów
                return hist.prepared_many(Body(f'{Path(path).stem} {i + 1}', w, 'sketch', 'XY', folder=folder) for i, w in enumerate(wires))
            self.run_operation('Importowanie SVG', build_svg, self.add_prepared_many, True)
            return

        def build():
            shapes = kernel.import_shapes(path)
            folder = Path(path).stem[:60] if len(shapes) > 1 and all(kind == 'sketch' for _, kind in shapes) else ''
            return hist.prepared_many(Body(Path(path).stem if i == 0 else f'{Path(path).stem} {i + 1}', s, kind, folder=folder)
                                      for i, (s, kind) in enumerate(shapes))

        def add(bodies):
            if not bodies:
                raise kernel.CadError('Plik nie zawiera obsługiwanej geometrii.')
            self.document.commit((*self.document.bodies, *bodies))
            self._tool_select([b.id for b in bodies])

        self.run_operation('Importowanie modelu', build, add, True)

    # =====================================================================
    # biblioteka obiektów i szkiców (zakładka Biblioteka)
    # =====================================================================
    def open_library(self, kind):
        from .library import LibraryDialog
        if self.busy:
            return
        dialog = self.libraries.get(kind)
        if dialog is None:
            dialog = self.libraries[kind] = LibraryDialog(self, kind)
        dialog.refresh()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def library_pick(self, dialog):
        """Wstaw z pola roboczego: okno chowa się, kliknięty obiekt (bryła albo szkic) trafia do bieżącego folderu."""
        if self.busy:
            return
        self.set_mode(None)
        dialog.hide()
        self._lib_action = dict(kind='pick', dialog=dialog)
        what = 'bryłę' if dialog.kind == 'object' else 'szkic'
        self.toast(f'Kliknij {what} na polu roboczym, aby zapisać ją w bibliotece · prawy przycisk albo Esc - anuluj.', 6000)

    def library_place(self, dialog, path):
        """Wstaw na pole robocze: element z biblioteki idzie za kursorem, kliknięcie stawia go w tym miejscu."""
        from . import library
        if self.busy:
            return
        self.set_mode(None)
        dialog.hide()

        def load():
            try:
                return library.load_bodies(dialog.kind, path)
            except Exception as exc:          # błąd odczytu: komunikat i powrót do okna biblioteki
                return str(exc) or 'Nie można odczytać pliku.'

        def start(bodies):
            if isinstance(bodies, str):
                raise kernel.CadError(bodies)
            if not bodies:
                raise kernel.CadError('Plik nie zawiera obsługiwanej geometrii.')
            meshes = [b.mesh for b in bodies if b.mesh is not None]
            lows, highs = zip(*(self._mesh_bounds(m) for m in meshes)) if meshes else ((np.zeros(3),), (np.zeros(3),))
            low, high = np.min(lows, axis=0), np.max(highs, axis=0)
            # punkt zaczepienia: obiekt stoi spodem na wskazanym miejscu, szkic - środkiem
            sketch = next((b for b in bodies if b.kind == 'sketch'), None)
            normal = np.array(kernel.frame_of(sketch.plane).normal, float) if sketch is not None else np.array([0.0, 0.0, 1.0])
            self._lib_action = dict(kind='place', dialog=dialog, bodies=bodies, low=np.asarray(low, float), high=np.asarray(high, float),
                                    normal=normal, name=library.display_name(path), mesh=_merge_meshes(meshes) if meshes else None)
            self.toast('Kliknij miejsce na polu roboczym (ścianę, płaszczyznę albo podłoże) · prawy przycisk albo Esc - anuluj.', 6000)

        def failed_back():
            if self._lib_action is None and not dialog.isVisible():
                dialog.show()

        self.run_operation('Wczytywanie z biblioteki', load, start, after=failed_back)

    def library_cancel(self):
        action = self._lib_action
        self._library_end()
        if action is not None:
            self.toast('Anulowano.', 1500)
            action['dialog'].show()
            action['dialog'].raise_()

    def _library_target(self, x, y):
        """Miejsce pod kursorem: (punkt, normalna, opis). Wierzchołek, ściana bryły, płaszczyzna albo podłoże - podłoże
        przyciągane do kratki siatki (krok zależny od powiększenia)."""
        vertex = self.view.nearest_vertex(x, y, solids_only=False)
        if vertex is not None:
            return np.array(vertex[1], float), np.array([0.0, 0.0, 1.0]), 'Wierzchołek'
        hit = self.view.pick_face(x, y)
        if hit is not None:
            return np.array(hit[2], float), np.asarray(hit[1], float), 'Ściana'
        name = self.view.plane_at(x, y)
        found = self.view._plane_hit(name, x, y) if name else None
        if found:
            return np.array(found[1], float), np.array(kernel.frame_of(name).normal, float), f'Płaszczyzna {name}'
        ray = self.view._ray(x, y)
        ground = self.view._ray_plane(ray, np.zeros(3), np.array([0.0, 0.0, 1.0])) if ray is not None else None
        if ground is None:
            return None
        step = 10 ** math.floor(math.log10(max(float(self.view.opts['distance']) / 40, 1e-3)))
        point = np.array([round(ground[0] / step) * step, round(ground[1] / step) * step, 0.0])
        return point, np.array([0.0, 0.0, 1.0]), 'Siatka'

    def _library_pose(self, x, y):
        """Położenie wstawianego elementu: obiekt dotyka wskazanej ściany / siatki od zewnątrz (bez obracania),
        szkic kładzie się środkiem na ścianie albo płaszczyźnie (obrócony do niej)."""
        action = self._lib_action
        found = self._library_target(x, y)
        if found is None:
            return None
        point, normal, label = found
        normal = normal / max(np.linalg.norm(normal), 1e-12)
        low, high = action['low'], action['high']
        centre, half = (low + high) / 2, (high - low) / 2
        rotation = np.eye(3)
        if action['dialog'].kind == 'sketch':
            if label != 'Siatka':
                rotation = kernel.rotation_between(action['normal'], normal)
            translation = point - rotation @ centre
        else:
            reach = float(np.abs(half) @ np.abs(normal))
            translation = point - (centre - normal * reach)
        return rotation, translation, point, label

    def _library_hover(self, x, y):
        action = self._lib_action
        if action['kind'] == 'pick':           # podświetlenie obiektu, który zostanie dodany po kliknięciu
            bid = self.pick_object(x, y)
            body = self.document.get(bid) if bid else None
            want = 'solid' if action['dialog'].kind == 'object' else 'sketch'
            hover = bid if body is not None and body.kind == want else ''
            if hover != self._obj_hover:
                self._obj_hover = hover
                self.refresh()
            self.view.setCursor(Qt.PointingHandCursor if hover else Qt.ArrowCursor)
            return
        if action['mesh'] is None:
            return
        pose = self._library_pose(x, y)
        if pose is None:
            self.view.set_marker(None)
            return
        rotation, translation, point, label = pose
        mesh = action['mesh']
        r, t = rotation.astype(np.float32), translation.astype(np.float32)
        moved = kernel.DisplayMesh(mesh.vertices @ r.T + t, mesh.triangles, {k: v @ r.T + t for k, v in mesh.edges.items()},
                                   tuple(float(c) for c in rotation @ np.asarray(mesh.center, float) + translation), mesh.size)
        self.view.set_preview_mesh(moved, color=(.3, .62, .95, .45), line_color=(.12, .36, .7, 1), width=1.6)
        self.view.set_marker(point, label=label)          # miejsce na siatce / ścianie, w którym stanie element

    def _library_click(self, x, y):
        from . import library
        action = self._lib_action
        dialog = action['dialog']
        if action['kind'] == 'pick':
            bid = self.pick_object(x, y)
            body = self.document.get(bid) if bid else None
            want = 'solid' if dialog.kind == 'object' else 'sketch'
            if body is None or body.kind != want:
                self.toast('Kliknij ' + ('bryłę.' if want == 'solid' else 'szkic.') + ' (prawy przycisk albo Esc - anuluj)', 3000)
                return
            ids = list(self._group_ids(bid))
            group = hist.text_group_of(bid)
            if group:                       # napis: wszystkie litery razem
                ids += [b.id for b in self.document.bodies if hist.text_group_of(b.id) == group and b.id not in ids]
            from . import plywood as pw
            plywood = pw.is_panel(body) and (body.folder or (body.meta or {}).get('ply', {}).get('fold'))
            if plywood:                     # płyta pudełka / mebla: zapisuje się całość (z pamięcią rozłożenia)
                ids += [i for i in self._ply_fold_ids([bid]) if i not in ids]
            members = [self.document.get(i) for i in ids if self.document.get(i) is not None]
            name = body.folder if ((group or plywood) and body.folder) else body.name.split(' — szyk')[0]
            try:
                path = library.save_bodies(members, dialog.folder, name)
            except Exception as exc:
                self.toast(f'Nie udało się zapisać w bibliotece: {exc}', 5000)
                return
            self._library_end()
            dialog.picked(path)
            return
        pose = self._library_pose(x, y)
        if pose is None:
            self.toast('Kliknij miejsce na polu roboczym.')
            return
        self._library_end()
        self._library_insert(action, pose[0], pose[1])
        dialog.show()
        dialog.raise_()

    def _library_end(self):
        self._lib_action = None
        self.view.set_preview_mesh(None)
        self.view.set_marker(None)
        self.view.unsetCursor()
        if self._obj_hover:
            self._obj_hover = ''
            self.refresh()

    def _library_insert(self, action, rotation, translation):
        """Kopie elementu z biblioteki ustawione na wskazanym miejscu (nowe identyfikatory, wspólna grupa / folder)."""
        groups = {}
        made = []
        for b in action['bodies']:
            plane = b.plane
            if b.kind == 'sketch':
                frame = kernel.frame_of(plane)
                plane = kernel.Frame(tuple(float(c) for c in rotation @ np.asarray(frame.origin, float) + translation),
                                     tuple(float(c) for c in rotation @ np.asarray(frame.xdir, float)),
                                     tuple(float(c) for c in rotation @ np.asarray(frame.normal, float)))
            group = groups.setdefault(b.group, ('sheet-' if b.group.startswith('sheet-') else '') + uuid.uuid4().hex) if b.group else ''
            shape = kernel.transformed(b.shape, rotation, translation)
            if b.kind == 'sketch':
                made.append(Body(b.name, shape, b.kind, plane, group=group, meta=b.meta))
            else:
                # bryła przenosi swoje dane: gwinty kosmetyczne i przepis blachy (dalej daje się rozkładać i zginać)
                matrix = np.column_stack([rotation, translation])
                made.append(replace(b, id=uuid.uuid4().hex, group=group, mesh=None).placed(shape, matrix))
        folder = action['name'] if len(made) > 1 else ''
        made = [replace(b, folder=folder) for b in made]
        ids = {old.id: new.id for old, new in zip(action['bodies'], made)}       # ścianki na noski / połączenia płyt - nowe id
        for i, b in enumerate(made):
            ply = ((b.meta or {}).get('ply') or {})
            if ply.get('tab') or ply.get('joined'):
                ply = dict(ply)
                if ply.get('tab'):
                    ply['tab'] = dict(ply['tab'], sheet=ids.get(ply['tab'].get('sheet'), ply['tab'].get('sheet')))
                if ply.get('joined'):
                    ply['joined'] = [ids.get(j, j) for j in ply['joined']]
                made[i] = replace(b, meta=dict(b.meta, ply=ply))
        keys = {}                      # każda wstawiona kopia pudełka dostaje własny klucz rozłożenia
        for i, b in enumerate(made):
            fold = ((b.meta or {}).get('ply') or {}).get('fold')
            if fold:
                key = keys.setdefault(fold.get('key'), uuid.uuid4().hex)
                made[i] = replace(b, meta=dict(b.meta, ply=dict(b.meta['ply'], fold=dict(fold, key=key))))

        def add(bodies):
            self.document.pending_label, self.document.pending_icon = f'Z biblioteki: {action["name"]}', 'libobj'
            self.document.commit((*self.document.bodies, *bodies))
            self._tool_select([b.id for b in bodies])

        self.run_operation('Wstawianie z biblioteki', lambda: [b.prepared() for b in made], add)

    def import_svg(self):
        self.import_model()

    def export_bodies(self):
        """Co trafia do eksportu: tylko obiekty widoczne na polu roboczym (bez ukrytych na liście obiektów i wygaszonych
        szkiców); gdy któreś z nich są zaznaczone - tylko zaznaczone."""
        hidden = self.shown_hidden()
        visible = [b for b in self.document.bodies if b.id not in hidden]
        chosen = [b for b in visible if b.id in self.selected]
        return chosen or visible

    def export_model(self):
        bodies = self.export_bodies()
        if not bodies:
            self.toast('Brak widocznych obiektów do eksportu.')
            return
        n = len(bodies)
        self.toast(f'Eksport: {"zaznaczone" if any(b.id in self.selected for b in bodies) else "widoczne"} obiekty ({n}).', 2500)
        path, _ = QFileDialog.getSaveFileName(self, 'Eksportuj zaznaczone lub widoczne obiekty', 'Model.step',
                                              'STEP (*.step);;STL (*.stl);;BREP (*.brep);;DXF — szkice (*.dxf)')
        if path:
            self.export_in_background(bodies, path)

    def export_in_background(self, bodies, path):
        """Eksport w tle bez blokowania pracy: bryły z gwintami dostają prawdziwe zwoje (do druku 3D i STEP) w procesie
        liczącym; w tym czasie można normalnie pracować dalej (eksportuje się stan z chwili wybrania pliku)."""
        from . import threads as th
        items = [(b.shape, tuple(b.threads)) for b in bodies]
        threaded = sum(len(t) for _, t in items)
        name = Path(path).name

        def job():
            try:
                return workers.call_any(th.export_job, items, path)
            except workers.Unavailable:
                return th.export_job(items, path)

        work = _Work(job)
        self._exports = getattr(self, '_exports', 0) + 1
        jobs = self.__dict__.setdefault('_export_jobs', [])
        jobs.append(work)                      # obiekt sygnałów musi żyć do końca pracy w tle

        def finished():
            self._exports -= 1
            if work in jobs:
                jobs.remove(work)

        def done(failed):
            finished()
            if failed:
                self.toast(f'Zapisano {name}. {failed} gwint(ów) nie udało się zbudować - zostały jako otwór.', 6000)
            else:
                self.toast(f'Zapisano {name}' + (f' (gwinty: {threaded}, jako prawdziwe zwoje).' if threaded else '.'), 4000)

        def failed(message):
            finished()
            self.toast(f'Eksport {name} nie powiódł się: {message}', 6000)

        work.signals.done.connect(done)
        work.signals.failed.connect(failed)
        self.pool.start(work)
        self.toast(f'Eksport {name} w tle' + (' - buduję prawdziwe gwinty, możesz dalej pracować.' if threaded else '…'), 4000)

    # =====================================================================
    # klawiatura
    # =====================================================================
    def keyPressEvent(self, event):
        key = event.key()
        if event.modifiers() & Qt.AltModifier and not self.busy and key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End):
            {Qt.Key_Left: lambda: self.history_step(-1), Qt.Key_Right: lambda: self.history_step(1),
             Qt.Key_Home: lambda: self.history_step(0, True), Qt.Key_End: lambda: self.history_step(10 ** 6, True)}[key]()
            event.accept()
            return
        if key == Qt.Key_Escape and self.section_picking:
            self.section_cancel_pick();event.accept();return
        if key == Qt.Key_Escape and self._lib_action is not None:
            self.library_cancel()
            event.accept()
            return
        if key == Qt.Key_Escape and self._repick is not None and not self.busy:
            self._repick = None
            self.history_goto(len(self.document.infos()[0]) - 1)
            self.toast('Anulowano ponowne wskazywanie.', 2500)
            event.accept()
            return
        if self.busy:
            if key == Qt.Key_Escape and self._hist_job is not None:
                self._hist_job['cancel'] = True
                self.toast('Przerywam przeliczanie historii…', 2000)
                event.accept()
                return
            if key == Qt.Key_Escape and getattr(self, '_cancel_op', None) is not None:
                self._cancel_op()
                event.accept()
                return
            super().keyPressEvent(event)
            return
        if self.mode == 'sketch' and key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            focus = QApplication.focusWidget()
            if not isinstance(focus, (QLineEdit, QDoubleSpinBox, QPlainTextEdit, QComboBox)) and pan_arrow(self.view, event):
                event.accept()          # strzałki w szkicu przesuwają widok
                return
        if self.mode == 'sketch':
            if key in (Qt.Key_Return, Qt.Key_Enter) and self.tool == 'line' and self.points and not self.dim_panel.isVisible():
                self.finish_line()
                event.accept()
                return
            text = event.text()
            if text and text in '0123456789.,-' and self.points and not self.dim_panel.isVisible() and self.open_dim_input(text):
                event.accept()
                return
        if key == Qt.Key_Tab and self.dim_panel.isVisible():
            edits = [e for e in self.dim_edits if e.isVisible()]
            if len(edits) > 1:
                (edits[1] if edits[0].hasFocus() else edits[0]).setFocus()
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            action = {'extrude': self.apply_extrude, 'revolve': self.apply_revolve, 'shell': self.apply_shell, 'sweep': self.apply_sweep, 'loft': self.apply_loft, 'bool': self.apply_bool, 'mod': self.apply_mod, 'split': self.apply_split, 'mirror': self.apply_mirror, 'pattern': self.apply_pattern,
                      'move': self.apply_transform, 'rotate': self.apply_transform, 'mate': self.apply_mate, 'align': self.apply_mate, 'scale': self.apply_scale,
                      'ply': self.apply_ply_panel, 'ply_wall': self.apply_ply_wall, 'ply_between': self.apply_ply_between, 'ply_joints': self.apply_ply_joints}.get(self.mode)
            if action is None and self.mode == 'sketch' and self.tool == 'text' and self.txt and self.txt['stage'] == 'edit':
                action = self.apply_text
            if action is None and self.mode == 'sketch' and self.tool == 'offset' and self.off is not None:
                action = self.apply_offset
            if action:
                action()
                event.accept()
                return
        if key == Qt.Key_Escape:
            if self.dim_panel.isVisible():
                self.dim_panel.hide()
                self.view.setFocus()
            elif self.mode == 'sketch' and (self.points or self.tangent_lines):
                self.end_current_shape()
            elif self.mode == 'sketch' and self.tool is None and self.selected:
                self.selected = []
                self.refresh()
                self._update_grips()
            elif self.mode == 'sketch' and self.tool == 'text':
                self.text_cancel()
            elif self.mode == 'sketch' and self.tool == 'offset' and self.off is not None:
                self.cancel_offset()
            elif self.mode is not None:
                self.set_mode(None)
            else:
                self.selected = []
                self.refresh()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.busy:
            self.toast('Trwa operacja — poczekaj na jej zakończenie.')
            event.ignore()
            return
        if not self.document.dirty:
            QApplication.instance().removeEventFilter(self)
            event.accept()
            return
        answer = QMessageBox.question(self, 'Niezapisane zmiany', 'Projekt ma niezapisane zmiany. Zapisać przed zamknięciem?',
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Discard:
            event.accept()
        elif answer == QMessageBox.Save:
            path = self.document.path
            if path is None:
                value, _ = QFileDialog.getSaveFileName(self, 'Zapisz projekt', 'Projekt.rccadx', 'RCCAD (*.rccadx)')
                if not value:
                    event.ignore()
                    return
                path = Path(value)
                if path.suffix.lower() != '.rccadx':
                    path = path.with_suffix('.rccadx')
            try:
                self.document.save(path)
            except Exception as exc:
                QMessageBox.warning(self, 'Zapis nie powiódł się', str(exc))
                event.ignore()
                return
            event.accept()
        else:
            event.ignore()
