"""Tekstury geometryczne - okno narzędzia (zakładka Wzory → Tekstury geometryczne): wybór powierzchni, galeria wzorów z miniaturami,
parametry zależne od wzoru, obszar i wykluczenia, gradienty, wzór własny, obraz jako mapa wysokości, podgląd na żywo, biblioteka.
Geometria: tex_engine (krok historii 'tex')."""
from __future__ import annotations

import copy
import uuid

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout)

from . import kernel
from . import shell_ui as ui
from . import tex_engine as te
from . import tex_library as lib
from . import tex_patterns as tp
from . import vent_feature as vf
from .enclosure_ui import _label, _spin
from .vent_ui import _Section

_STATE = {'cancel': False, 'progress': 0.0}
LEVELS = {'fast': 'Szybki podgląd (obrysy na powierzchni)', 'spatial': 'Podgląd przestrzenny (bryły elementów)', 'exact': 'Dokładny podgląd (wynik operacji)'}
FIELD = {f[0]: f for f in tp.FIELDS}
ALWAYS = ('min_wall', 'tol')
GRAD_PARAMS = {'height': 'Wysokość', 'depth': 'Głębokość', 'size': 'Wielkość elementów', 'spacing': 'Rozstaw', 'density': 'Gęstość', 'angle': 'Kąt', 'wall': 'Grubość ścianki'}
GRAD_FIELDS = (('v0', 'Wartość na początku', 1.0, -1000, 1000, 2, .1, ''), ('v1', 'Wartość na końcu', .5, -1000, 1000, 2, .1, ''),
               ('angle', 'Kierunek gradientu', 0.0, -360, 360, 1, 5, ' °'), ('length', 'Długość gradientu', 50.0, .1, 1e4, 2, 1, ' mm'))
REGION_LABELS = dict(te.REGION_LABELS)
IMG_FIELDS = (('min_h', 'Wysokość minimalna', 0.0, -100, 100, 2, .1, ' mm'), ('max_h', 'Wysokość maksymalna', 1.0, -100, 100, 2, .1, ' mm'),
              ('contrast', 'Kontrast', 1.0, .1, 10, 2, .1, '×'), ('smooth', 'Wygładzanie (iteracje)', 0, 0, 20, 0, 1, ''),
              ('threshold', 'Próg (0 = ciągły)', 0.0, 0, 1, 2, .05, ''), ('scale', 'Skala obrazu', 1.0, .05, 50, 2, .1, '×'),
              ('rotate', 'Obrót obrazu', 0.0, -360, 360, 1, 5, ' °'), ('tile_x', 'Powtórzenia poziomo', 1, 1, 500, 0, 1, ''),
              ('tile_y', 'Powtórzenia pionowo', 1, 1, 500, 0, 1, ''), ('cell', 'Rozdzielczość siatki (0 = auto)', 0.0, 0, 50, 2, .1, ' mm'))


class TextureTools:
    # ------------------------------------------------------------------ panel
    def _build_tex_panel(self):
        self.xt = self._tex_fresh()
        self._xt_timer = QTimer(self)
        self._xt_timer.setSingleShot(True)
        self._xt_timer.setInterval(300)
        self._xt_timer.timeout.connect(lambda: self._xt_preview())
        self._xt_poll = QTimer(self)
        self._xt_poll.setInterval(250)
        self._xt_poll.timeout.connect(lambda: self.xt_bar.setValue(int(100 * _STATE['progress'])))
        self._xt_block = False
        self.xt_panel, lay = self._panel(340, 'Tekstury geometryczne', 'x_tex', 'Powierzchnie → wzór → parametry → Zastosuj', plain=True, scroll=True)
        self.xt_step1 = ui.StepRow(1, 'x_tex', 'Powierzchnie', plain=True)
        lay.addWidget(self.xt_step1)
        self.xt_w = {}                                  # klucz → (etykieta, pole)
        self.xt_c = {}                                  # klucz → (etykieta, lista)
        self.xt_b = {}                                  # klucz → pole wyboru
        self.xt_gw = {}
        self.xt_iw = {}

        def section(title, opened=False):
            s = _Section(title, opened)
            lay.addWidget(s)
            return s.inner

        def combo(box_lay, key, items, store=None):
            box = QComboBox()
            for k_, t_ in items.items():
                box.addItem(t_, k_)
            box.currentIndexChanged.connect(lambda *_, k_=key: self._xt_changed(k_))
            box_lay.addWidget(box)
            (store if store is not None else self.xt_c)[key] = box
            return box

        def numeric(grid, n, key, title, lo, hi, dec, step, suf, store, cb):
            box = _spin(0.0, float(lo), float(hi), dec, step, suf)
            box.valueChanged.connect(lambda *_, k_=key: cb(k_))
            lab = _label(title, 'label')
            grid.addWidget(lab, n, 0)
            grid.addWidget(box, n, 1)
            store[key] = (lab, box)

        # 1. powierzchnie
        s = section('1. Powierzchnie', True)
        self.xt_faces = _label('Kliknij ścianę bryły (Shift - kolejne ściany).', 'value')
        self.xt_faces.setWordWrap(True)
        s.addWidget(self.xt_faces)
        row = QHBoxLayout()
        for title, fn in (('Wybieraj ściany', lambda: self._xt_pick('faces')), ('Wyczyść', self._xt_clear_faces)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        s.addLayout(row)
        combo(s, 'multi', te.MULTI_LABELS)
        combo(s, 'mapping', su_mapping_labels())
        # 2. wzór
        s = section('2. Wzór', True)
        self.xt_search = QLineEdit()
        self.xt_search.setPlaceholderText('Szukaj wzoru lub konfiguracji…')
        self.xt_search.textChanged.connect(lambda *_: self._xt_gallery_fill())
        s.addWidget(self.xt_search)
        self.xt_cat = QComboBox()
        for k_, t_ in lib.CATEGORY_LABELS.items():
            self.xt_cat.addItem(t_, k_)
        self.xt_cat.setCurrentIndex(2)
        self.xt_cat.currentIndexChanged.connect(lambda *_: self._xt_gallery_fill())
        s.addWidget(self.xt_cat)
        self.xt_gal = QListWidget()
        self.xt_gal.setViewMode(QListView.IconMode)
        self.xt_gal.setIconSize(QSize(56, 56))
        self.xt_gal.setGridSize(QSize(78, 92))
        self.xt_gal.setResizeMode(QListView.Adjust)
        self.xt_gal.setWordWrap(True)
        self.xt_gal.setFixedHeight(230)
        self.xt_gal.itemClicked.connect(lambda it: self._xt_gallery_apply(it))
        s.addWidget(self.xt_gal)
        combo(s, 'mode', tp.MODE_LABELS)
        combo(s, 'accuracy', tp.COMBO['accuracy'])
        self.xt_accuracy_note = _label('', 'value')
        self.xt_accuracy_note.setWordWrap(True)
        s.addWidget(self.xt_accuracy_note)
        # 3. parametry wzoru
        s = section('3. Parametry wzoru', True)
        self.xt_pat_box = s
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        n = 0
        combos_first = [k for k in tp.COMBO if k not in ('accuracy', 'fit', 'boundary')]
        for key in combos_first:
            box = QComboBox()
            for k_, t_ in tp.COMBO[key].items():
                box.addItem(t_, k_)
            box.currentIndexChanged.connect(lambda *_, k_=key: self._xt_changed(k_))
            grid.addWidget(box, n, 0, 1, 2)
            self.xt_c[key] = box
            n += 1
        specific = [f for f in tp.FIELDS if f[0] not in tp.COMMON_USE and f[0] not in ALWAYS]
        for key, title, lo, hi, dec, step, suf in specific:
            numeric(grid, n, key, title, lo, hi, dec, step, suf, self.xt_w, self._xt_changed)
            n += 1
        for key, title in tp.BOOL.items():
            if key in ('reverse', 'mirror', 'protect_wall'):
                continue
            cb = QCheckBox(title)
            cb.toggled.connect(lambda *_, k_=key: self._xt_changed(k_))
            grid.addWidget(cb, n, 0, 1, 2)
            self.xt_b[key] = cb
            n += 1
        for key in ('alternate',):
            if key not in self.xt_b:
                cb = QCheckBox('Naprzemienne odwracanie')
                cb.toggled.connect(lambda *_, k_=key: self._xt_changed(k_))
                grid.addWidget(cb, n, 0, 1, 2)
                self.xt_b[key] = cb
                n += 1
        s.addLayout(grid)
        # 4. rozmieszczenie
        s = section('4. Rozmieszczenie i dopasowanie', True)
        combo(s, 'fit', tp.COMBO['fit'])
        combo(s, 'boundary', tp.COMBO['boundary'])
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        for n, (key, title, lo, hi, dec, step, suf) in enumerate(f for f in tp.FIELDS if f[0] in tp.COMMON_USE):
            numeric(grid, n, key, title, lo, hi, dec, step, suf, self.xt_w, self._xt_changed)
        s.addLayout(grid)
        for key in ('reverse', 'mirror'):
            cb = QCheckBox(tp.BOOL[key])
            cb.toggled.connect(lambda *_, k_=key: self._xt_changed(k_))
            s.addWidget(cb)
            self.xt_b[key] = cb
        row = QHBoxLayout()
        b = QPushButton('Wskaż punkt początkowy')
        b.clicked.connect(lambda _=False: self._xt_pick('origin'))
        row.addWidget(b)
        b = QPushButton('Usuń punkt')
        b.clicked.connect(lambda _=False: self._xt_set_origin(None))
        row.addWidget(b)
        s.addLayout(row)
        # 5. obszar i wykluczenia
        s = section('5. Obszar i wykluczenia')
        combo(s, 'rtype', REGION_LABELS)
        grid = QGridLayout()
        self.xt_rw = {}
        for n, (key, title, val, lo, hi) in enumerate((('cx', 'Środek X', 0.0, -1e4, 1e4), ('cy', 'Środek Y', 0.0, -1e4, 1e4), ('w', 'Szerokość', 40.0, .5, 1e4),
                                                       ('h', 'Wysokość', 30.0, .5, 1e4), ('d', 'Średnica', 40.0, .5, 1e4), ('sides', 'Liczba boków', 6, 3, 64),
                                                       ('angle', 'Obrót', 0.0, -360, 360))):
            box = _spin(float(val), float(lo), float(hi), 0 if key == 'sides' else 2, .5, '')
            box.valueChanged.connect(lambda *_, k_=key: self._xt_region_changed(k_))
            lab = _label(title, 'label')
            grid.addWidget(lab, n, 0)
            grid.addWidget(box, n, 1)
            self.xt_rw[key] = (lab, box)
        s.addLayout(grid)
        self.xt_region_pick = QPushButton('Wskaż szkic obszaru')
        self.xt_region_pick.clicked.connect(lambda _=False: self._xt_pick('region_sketch'))
        s.addWidget(self.xt_region_pick)
        self.xt_zones = QListWidget()
        self.xt_zones.setFixedHeight(54)
        s.addWidget(self.xt_zones)
        row = QHBoxLayout()
        for title, fn in (('Wyklucz szkic', lambda: self._xt_pick('zone_sketch')), ('Usuń wykluczenie', self._xt_zone_remove)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        s.addLayout(row)
        # 6. gradienty
        s = section('6. Gradienty')
        self.xt_glist = QListWidget()
        self.xt_glist.setFixedHeight(54)
        self.xt_glist.currentRowChanged.connect(lambda r: self._xt_grad_select(r))
        s.addWidget(self.xt_glist)
        row = QHBoxLayout()
        for title, fn in (('Dodaj gradient', self._xt_grad_add), ('Usuń gradient', self._xt_grad_remove)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        s.addLayout(row)
        self.xt_gparam = combo(s, 'g_param', GRAD_PARAMS, self.xt_gw)
        self.xt_gtype = combo(s, 'g_type', te.GRADIENT_TYPES, self.xt_gw)
        grid = QGridLayout()
        for n, (key, title, val, lo, hi, dec, step, suf) in enumerate(GRAD_FIELDS):
            box = _spin(float(val), float(lo), float(hi), dec, step, suf)
            box.valueChanged.connect(lambda *_, k_=key: self._xt_grad_changed(k_))
            grid.addWidget(_label(title, 'label'), n, 0)
            grid.addWidget(box, n, 1)
            self.xt_gw[key] = box
        s.addLayout(grid)
        b = QPushButton('Wskaż szkic krzywej gradientu')
        b.clicked.connect(lambda _=False: self._xt_pick('grad_curve'))
        s.addWidget(b)
        self.xt_gnote = _label('Wartości dotyczą wybranego parametru (np. wysokość w mm, wielkość w mm, gęstość ×, kąt w °).', 'value')
        self.xt_gnote.setWordWrap(True)
        s.addWidget(self.xt_gnote)
        # 7. wzór własny i obraz
        s = section('7. Wzór własny i obraz (mapa wysokości)')
        row = QHBoxLayout()
        for title, fn in (('Element ze szkicu', lambda: self._xt_pick('custom_sketch')), ('Element z bryły', lambda: self._xt_pick('custom_body')),
                          ('Plik SVG / DXF', self._xt_import_file)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        s.addLayout(row)
        self.xt_custom_info = _label('Element własny: brak.', 'value')
        self.xt_custom_info.setWordWrap(True)
        s.addWidget(self.xt_custom_info)
        row = QHBoxLayout()
        for title, fn in (('Wczytaj obraz PNG / JPG / BMP…', self._xt_load_image), ('Usuń obraz', self._xt_clear_image)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        s.addLayout(row)
        self.xt_invert = QCheckBox('Odwróć jasność obrazu')
        self.xt_invert.toggled.connect(lambda *_: self._xt_image_changed('invert'))
        s.addWidget(self.xt_invert)
        grid = QGridLayout()
        for n, (key, title, val, lo, hi, dec, step, suf) in enumerate(IMG_FIELDS):
            box = _spin(float(val), float(lo), float(hi), dec, step, suf)
            box.valueChanged.connect(lambda *_, k_=key: self._xt_image_changed(k_))
            grid.addWidget(_label(title, 'label'), n, 0)
            grid.addWidget(box, n, 1)
            self.xt_iw[key] = box
        s.addLayout(grid)
        self.xt_image_info = _label('Obraz: brak (mapa wysokości powstaje z jasności pikseli - nie z bryły na piksel).', 'value')
        self.xt_image_info.setWordWrap(True)
        s.addWidget(self.xt_image_info)
        # 8. zabezpieczenia
        s = section('8. Zabezpieczenia i dokładność')
        cb = QCheckBox(tp.BOOL['protect_wall'])
        cb.toggled.connect(lambda *_: self._xt_changed('protect_wall'))
        s.addWidget(cb)
        self.xt_b['protect_wall'] = cb
        grid = QGridLayout()
        for n, key in enumerate(('min_wall', 'tol', 'mixed_pct')):
            f = FIELD[key]
            numeric(grid, n, key, f[1], f[2], f[3], f[4], f[5], f[6], self.xt_w, self._xt_changed)
        s.addLayout(grid)
        # 9. biblioteka konfiguracji
        s = section('9. Konfiguracje')
        row = QHBoxLayout()
        for title, fn in (('Zapisz konfigurację', self.tex_save_template), ('Wczytaj…', self.tex_load_template)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        s.addLayout(row)
        row = QHBoxLayout()
        for title, fn in (('Zapisz do pliku', self.tex_save_file), ('Otwórz z pliku', self.tex_open_file)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        s.addLayout(row)
        # 10. podgląd i statystyki
        s = section('10. Podgląd i statystyki', True)
        self.xt_stats = _label('', 'value')
        self.xt_stats.setWordWrap(True)
        s.addWidget(self.xt_stats)
        self.xt_level = QComboBox()
        for k_, t_ in LEVELS.items():
            self.xt_level.addItem(t_, k_)
        self.xt_level.setCurrentIndex(1)
        self.xt_level.currentIndexChanged.connect(lambda *_: self._xt_update())
        s.addWidget(self.xt_level)
        self.xt_bar = QProgressBar()
        self.xt_bar.setRange(0, 100)
        s.addWidget(self.xt_bar)
        row = QHBoxLayout()
        for title, fn in (('Przelicz podgląd', lambda: self._xt_preview(force=True)), ('Przerwij', lambda: _STATE.update(cancel=True)),
                          ('Resetuj parametry', self.tex_reset)):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            row.addWidget(b)
        s.addLayout(row)
        self.xt_info = _label('', 'value')
        self.xt_info.setWordWrap(True)
        lay.addWidget(self.xt_info)
        self.xt_status = _label('Kliknij ścianę bryły.', 'status')
        self.xt_status.setWordWrap(True)
        lay.addWidget(self.xt_status)
        self.xt_apply, _ = self._buttons(self.xt_panel.footer, 'Zastosuj', 'Anuluj', self.apply_tex, lambda: self.set_mode(None))
        self._xt_thumbs = {}
        return self.xt_panel

    # ------------------------------------------------------------------ stan
    @staticmethod
    def _tex_fresh():
        return dict(target=None, faces=[], p=copy.deepcopy(tp.DEFAULTS), region=dict(type='face'), exclusions=[], multi='independent', mapping='auto',
                    density=0.0, pick='faces', result=None, cur_grad=-1, out_ids=[], end_ref=None)

    def _tex_begin(self):
        self.xt = self._tex_fresh()
        self.xt_panel.show()
        self._xt_sync()
        self._xt_gallery_fill()
        self.hint('Tekstury: kliknij ścianę bryły (Shift - kolejne), wybierz wzór i ustaw parametry. Enter - Zastosuj, Esc - anuluj.')
        self.view.setCursor(Qt.PointingHandCursor)
        self._xt_update()

    def _xt_pick(self, what):
        self.xt['pick'] = what
        self.xt_status.setText({'faces': 'Klikaj ściany (Shift - dodaj).', 'region_sketch': 'Kliknij szkic z konturem obszaru.',
                                'zone_sketch': 'Kliknij szkic - obszar wykluczony.', 'custom_sketch': 'Kliknij szkic z konturem elementu.',
                                'custom_body': 'Kliknij bryłę, która ma być powtarzanym elementem.', 'origin': 'Kliknij punkt początkowy wzoru na powierzchni.',
                                'grad_curve': 'Kliknij szkic krzywej gradientu.'}.get(what, ''))

    def tex_hover(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        self.view.set_hover_mesh(body.mesh if body is not None and self.xt.get('pick') in ('faces', 'custom_body', 'region_sketch', 'zone_sketch', 'custom_sketch', 'grad_curve') else None)

    def tex_click(self, x, y, shift=False):
        pick = self.xt.get('pick', 'faces')
        if pick in ('region_sketch', 'zone_sketch', 'custom_sketch', 'grad_curve', 'custom_body'):
            hit = self.view.pick_body(x, y) if hasattr(self.view, 'pick_body') else None
            bid = hit if isinstance(hit, str) else (hit[0] if hit else None)
            body = self.document.get(bid) if bid else None
            if body is None:
                hit2 = self.view.pick_face(x, y)
                body = self.document.get(hit2[0]) if hit2 else None
            if body is None:
                return
            if pick == 'custom_body':
                if body.kind != 'solid':
                    self.toast('Element własny z bryły: kliknij bryłę.')
                    return
                self.xt['p'].update(custom_src='solid', custom_body=body.id, pattern='custom')
            else:
                if body.kind != 'sketch':
                    self.toast('Kliknij szkic.')
                    return
                if pick == 'region_sketch':
                    t = self.xt['region'].get('type')
                    self.xt['region'] = dict(self.xt['region'], type=t if t in ('sketch', 'sketch_out') else 'sketch', sketch=body.id)
                elif pick == 'zone_sketch':
                    self.xt['exclusions'].append(dict(type='sketch', id=body.id, name=body.name))
                elif pick == 'grad_curve':
                    gs = self.xt['p']['gradients']
                    if 0 <= self.xt['cur_grad'] < len(gs):
                        gs[self.xt['cur_grad']].update(type='curve', curve=body.id)
                else:
                    self._xt_custom_from_sketch(body)
            self.xt['pick'] = 'faces'
            self._xt_sync()
            self._xt_update()
            return
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None:
            return
        P, N = np.asarray(hit[2], float), np.asarray(hit[1], float)
        if pick == 'origin':
            if body.id != self.xt.get('target'):
                self.toast('Punkt początkowy wskaż na zaznaczonej bryle.')
                return
            self._xt_set_origin([float(v) for v in P])
            self.xt['pick'] = 'faces'
            return
        if body.kind != 'solid':
            self.toast('Teksturę nakłada się na ścianę bryły - kliknij bryłę.')
            return
        try:
            f, n = kernel.face_at(body.shape, N, P, curved=True)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        fw = f.wrapped if hasattr(f, 'wrapped') else f
        ref = vf.face_refs(body.shape, [fw])[0]
        ref['point'], ref['normal'] = [float(v) for v in P], [float(v) for v in (n if n is not None else N)]
        if self.xt.get('target') != body.id:
            self.xt['faces'] = []
        self.xt['target'] = body.id
        if not shift:
            self.xt['faces'] = []
        i = next((k for k, r in enumerate(self.xt['faces']) if np.allclose(r['centroid'], ref['centroid'], atol=1e-6)), None)
        if i is None:
            self.xt['faces'].append(ref)
        elif shift:
            self.xt['faces'].pop(i)
        self._xt_update()

    def _xt_clear_faces(self):
        self.xt.update(faces=[], target=None, result=None)
        self.view.set_preview_mesh(None)
        self._xt_update()

    def _xt_set_origin(self, P):
        self.xt['p']['origin'] = P
        if P is not None:
            self.xt['p']['fit'] = 'start'
        self._xt_sync()
        self._xt_update()

    # ------------------------------------------------------------------ pola
    def _xt_sync(self):
        """Wartości z self.xt do widżetów + widoczność pól zależna od wzoru."""
        self._xt_block = True
        p = self.xt['p']
        try:
            for k, (lab, box) in self.xt_w.items():
                box.setValue(float(p.get(k, 0)))
            for k, box in self.xt_c.items():
                if k in p:
                    v = p[k]
                elif k == 'multi':
                    v = self.xt['multi']
                elif k == 'mapping':
                    v = self.xt['mapping']
                elif k == 'rtype':
                    v = self.xt['region'].get('type', 'face')
                else:
                    continue
                i = box.findData(v)
                if i >= 0:
                    box.setCurrentIndex(i)
            for k, cb in self.xt_b.items():
                cb.setChecked(bool(p.get(k)))
            reg = self.xt['region']
            for k, (lab, box) in self.xt_rw.items():
                box.setValue(float(reg.get(k, box.value())))
            img = p.get('image') or {}
            for k, box in self.xt_iw.items():
                box.setValue(float(img.get(k, box.value())))
            self.xt_invert.setChecked(bool(img.get('invert')))
        finally:
            self._xt_block = False
        self._xt_refresh_lists()
        self._xt_visibility()

    def _xt_refresh_lists(self):
        self.xt_zones.clear()
        for z in self.xt['exclusions']:
            self.xt_zones.addItem(f'{z.get("type", "")}: {z.get("name", z.get("id", ""))}')
        self.xt_glist.blockSignals(True)
        self.xt_glist.clear()
        for g in self.xt['p'].get('gradients') or []:
            self.xt_glist.addItem(f'{GRAD_PARAMS.get(g.get("param"), g.get("param"))} - {te.GRADIENT_TYPES.get(g.get("type", "linear"), "")}')
        if 0 <= self.xt['cur_grad'] < self.xt_glist.count():
            self.xt_glist.setCurrentRow(self.xt['cur_grad'])
        self.xt_glist.blockSignals(False)
        p = self.xt['p']
        self.xt_custom_info.setText('Element własny: ' + ({'solid': 'bryła użytkownika', 'sketch': 'szkic / plik (%d konturów)' % len(p.get('custom_loops') or [])}.get(p.get('custom_src'), '-')))
        img = p.get('image')
        self.xt_image_info.setText(f'Obraz: {img.get("name", "")} ({img.get("w")}×{img.get("h")} px), mapa wysokości.' if img and img.get('data')
                                   else 'Obraz: brak (mapa wysokości powstaje z jasności pikseli - nie z bryły na piksel).')
        self._xt_grad_load()

    def _xt_visibility(self):
        p = self.xt['p']
        pat = p['pattern']
        use = set(tp.USE.get(pat, ())) | set(tp.COMMON_USE) | set(ALWAYS)
        if pat in ('waves', 'image'):
            use -= {'px', 'py', 'nx', 'ny', 'density', 'randomness'}
        for k, (lab, box) in self.xt_w.items():
            vis = k in use and not (k == 'mixed_pct' and p.get('mode') != 'mixed')
            if k == 'mixed_pct':
                vis = p.get('mode') == 'mixed'
            if k in ('height',) and p.get('mode') == 'concave' and pat not in ('waves',):
                vis = False
            if k in ('depth',) and p.get('mode') in ('convex', 'separate') and pat not in ('waves',):
                vis = False
            lab.setVisible(vis)
            box.setVisible(vis)
        for k, box in self.xt_c.items():
            if k in tp.COMBO and k not in ('accuracy', 'fit', 'boundary', 'mixed_rule'):
                box.setVisible(k in use)
            if k == 'mixed_rule':
                box.setVisible(p.get('mode') == 'mixed')
        for k, cb in self.xt_b.items():
            if k in ('reverse', 'mirror', 'protect_wall'):
                continue
            cb.setVisible(k in use or (k == 'wave2' and pat == 'waves'))
        self.xt_pat_box.parentWidget().setVisible(True)
        reg = self.xt['region'].get('type', 'face')
        show = {'face': (), 'rect': ('cx', 'cy', 'w', 'h', 'angle'), 'circle': ('cx', 'cy', 'd'), 'polygon': ('cx', 'cy', 'd', 'sides', 'angle'),
                'lasso': (), 'sketch': (), 'sketch_out': ()}.get(reg, ())
        for k, (lab, box) in self.xt_rw.items():
            lab.setVisible(k in show)
            box.setVisible(k in show)
        self.xt_region_pick.setVisible(reg in ('sketch', 'sketch_out'))
        acc = p.get('accuracy', 'exact')
        self.xt_accuracy_note.setText({'exact': 'Dokładny B-Rep: pełna edycja (zaokrąglenia, fazy, Boolean), eksport STEP.',
                                       'optimized': 'Zoptymalizowany B-Rep: prostsze powierzchnie elementów, szybszy dla wielu elementów; STEP.',
                                       'mesh': 'Siatkowy: wynik NIE jest B-Rep - eksport STL / 3MF, bez STEP i bez dalszej edycji ścian.'}[acc])

    def _xt_changed(self, key):
        if self._xt_block:
            return
        p = self.xt['p']
        if key in self.xt_w:
            p[key] = type(tp.DEFAULTS.get(key, 0.0))(self.xt_w[key][1].value()) if key in tp.DEFAULTS and isinstance(tp.DEFAULTS[key], (int, float)) and not isinstance(tp.DEFAULTS[key], bool) else self.xt_w[key][1].value()
        elif key in self.xt_b:
            p[key] = self.xt_b[key].isChecked()
        elif key in self.xt_c:
            v = self.xt_c[key].currentData()
            if key == 'multi':
                self.xt['multi'] = v
            elif key == 'mapping':
                self.xt['mapping'] = v
            elif key == 'rtype':
                self.xt['region'] = dict(self.xt['region'], type=v)
            elif key in ('g_param', 'g_type'):
                pass
            else:
                p[key] = v
        if key in ('mode', 'accuracy', 'custom_src', 'rtype'):
            self._xt_visibility()
        self._xt_update()

    def _xt_region_changed(self, key):
        if self._xt_block:
            return
        self.xt['region'][key] = self.xt_rw[key][1].value()
        self._xt_update()

    # ------------------------------------------------------------------ gradienty
    def _xt_grad_add(self):
        gs = self.xt['p'].setdefault('gradients', [])
        gs.append(dict(param='height', type='linear', v0=float(self.xt['p'].get('height', .6)), v1=float(self.xt['p'].get('height', .6)) * .3, angle=0.0, length=40.0))
        self.xt['cur_grad'] = len(gs) - 1
        self._xt_refresh_lists()
        self._xt_update()

    def _xt_grad_remove(self):
        gs = self.xt['p'].get('gradients') or []
        i = self.xt['cur_grad']
        if 0 <= i < len(gs):
            gs.pop(i)
        self.xt['cur_grad'] = len(gs) - 1
        self._xt_refresh_lists()
        self._xt_update()

    def _xt_grad_select(self, r):
        self.xt['cur_grad'] = r
        self._xt_grad_load()

    def _xt_grad_load(self):
        gs = self.xt['p'].get('gradients') or []
        i = self.xt['cur_grad']
        on = 0 <= i < len(gs)
        for w in self.xt_gw.values():
            w.setEnabled(on)
        if not on:
            return
        self._xt_block = True
        g = gs[i]
        for k in ('v0', 'v1', 'angle', 'length'):
            self.xt_gw[k].setValue(float(g.get(k, self.xt_gw[k].value())))
        for k, key in (('g_param', 'param'), ('g_type', 'type')):
            j = self.xt_gw[k].findData(g.get(key))
            if j >= 0:
                self.xt_gw[k].setCurrentIndex(j)
        self._xt_block = False

    def _xt_grad_changed(self, key):
        if self._xt_block:
            return
        gs = self.xt['p'].get('gradients') or []
        i = self.xt['cur_grad']
        if 0 <= i < len(gs):
            gs[i][key] = self.xt_gw[key].value()
            self._xt_update()

    # ------------------------------------------------------------------ wzór własny, obraz
    def _xt_custom_from_sketch(self, body):
        loops3 = vf._sketch_loops(body)
        if not loops3:
            raise kernel.CadError('Szkic nie ma zamkniętych konturów.')
        P = np.vstack(loops3)
        c = P.mean(0)
        u, s_, vt = np.linalg.svd(P - c)
        x, y = vt[0], vt[1]
        loops = [np.array([((q - c) @ x, (q - c) @ y) for q in lp]) for lp in loops3]
        self.xt['p'].update(custom_src='sketch', custom_loops=loops, custom_body=body.id, pattern='custom')

    def _xt_import_file(self, path=None):
        from .vent_ui import import_pattern
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self, 'Element wzoru z pliku', '', 'Rysunki (*.svg *.dxf)')
            if not path:
                return None
        try:
            loops, report = import_pattern(path)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return None
        pts = []
        for lp in loops:
            q = [np.asarray(seg[1], float) for seg in lp if seg and seg[0] == 'L']
            if len(q) >= 3:
                pts.append(np.array(q))
        self.xt['p'].update(custom_src='file', custom_loops=pts, custom_body=None, pattern='custom')
        self.xt_status.setText('; '.join(t for _l, t in report))
        self._xt_sync()
        self._xt_update()
        return report

    def _xt_load_image(self, path=None):
        from . import tex_relief as tr
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self, 'Obraz mapy wysokości', '', 'Obrazy (*.png *.jpg *.jpeg *.bmp)')
            if not path:
                return None
        try:
            img = tr.load_image(path)
        except Exception as exc:
            self.toast(f'Nie udało się wczytać obrazu: {exc}')
            return None
        self.xt['p']['image'] = dict(tr.IMG_DEFAULTS, **img)
        self.xt['p']['pattern'] = 'image'
        self._xt_sync()
        self._xt_update()
        return img

    def _xt_clear_image(self):
        self.xt['p']['image'] = None
        if self.xt['p']['pattern'] == 'image':
            self.xt['p']['pattern'] = 'knurl_cross'
        self._xt_sync()
        self._xt_update()

    def _xt_image_changed(self, key):
        if self._xt_block:
            return
        img = self.xt['p'].get('image')
        if not img:
            return
        img[key] = self.xt_invert.isChecked() if key == 'invert' else self.xt_iw[key].value()
        self._xt_update()

    def _xt_zone_remove(self):
        r = self.xt_zones.currentRow()
        if 0 <= r < len(self.xt['exclusions']):
            self.xt['exclusions'].pop(r)
            self._xt_sync()
            self._xt_update()

    # ------------------------------------------------------------------ galeria
    def _xt_gallery_items(self):
        cat = self.xt_cat.currentData()
        q = self.xt_search.text().strip().lower()
        items = []
        if cat in ('', 'pattern'):
            items += [(e['id'], e['label'], e['params']) for e in lib.pattern_entries()]
        if cat in ('', 'preset'):
            items += [(e['id'], e['label'], e['params']) for e in lib.PRESETS]
        if cat in ('', 'user'):
            items += [('tpl:' + t['name'], t['name'], (t.get('config') or {}).get('p') or {}) for t in lib.templates()]
        return [i for i in items if not q or q in i[1].lower()]

    def _xt_gallery_fill(self):
        self.xt_gal.clear()
        for iid, label, params in self._xt_gallery_items():
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, iid)
            it.setSizeHint(QSize(78, 92))
            if iid not in self._xt_thumbs:
                try:
                    self._xt_thumbs[iid] = QIcon(lib.thumbnail(params, 56))
                except Exception:
                    self._xt_thumbs[iid] = QIcon()
            it.setIcon(self._xt_thumbs[iid])
            self.xt_gal.addItem(it)

    def _xt_gallery_apply(self, item):
        iid = item.data(Qt.UserRole)
        keep = {k: self.xt['p'].get(k) for k in ('margin', 'margin_holes', 'accuracy', 'origin', 'image', 'custom_loops', 'custom_body', 'gradients')}
        if iid.startswith('pat:'):
            patch = dict(pattern=iid[4:])
            mode = self.xt['p'].get('mode', 'convex')
            self.xt['p'] = dict(tp.DEFAULTS, **{k: v for k, v in keep.items() if v is not None}, **patch, mode=mode)
            if patch['pattern'] in ('waves', 'image') and mode == 'separate':
                self.xt['p']['mode'] = 'convex'
        elif iid.startswith('tpl:'):
            t = next((x for x in lib.templates() if 'tpl:' + x['name'] == iid), None)
            if t:
                self._xt_apply_config(t.get('config') or {})
            return
        else:
            params = lib.preset(iid)
            if params:
                self.xt['p'] = dict(tp.DEFAULTS, **params)
        self._xt_sync()
        self._xt_update()

    # ------------------------------------------------------------------ przepis i podgląd
    def tex_recipe(self):
        if not self.xt.get('target') or not self.xt.get('faces'):
            return None
        p = copy.deepcopy(self.xt['p'])
        r = te.new_recipe(self.xt['target'], [dict(f) for f in self.xt['faces']], p=p, region=copy.deepcopy(self.xt['region']),
                          exclusions=copy.deepcopy(self.xt['exclusions']), multi=self.xt['multi'], mapping=self.xt['mapping'], density=self.xt['density'],
                          out_ids=list(self.xt.get('out_ids') or []))
        r['id'] = 'preview'
        return r

    def _xt_update(self):
        if not hasattr(self, 'xt_c') or self.mode != 'tex':
            return
        tb = self.document.get(self.xt.get('target') or '')
        n = len(self.xt['faces'])
        self.xt_step1.set_state('done' if n else 'active', f'{tb.name if tb else ""}: {n} ścian' if n else 'kliknij ścianę')
        self.xt_faces.setText(f'Zaznaczone ściany: {n}' + (f' ({", ".join(sorted({f.get("kind", "") for f in self.xt["faces"]}))})' if n else '') +
                              ('' if n else ' - kliknij ścianę bryły (Shift - kolejne).'))
        self.xt_apply.setEnabled(False)
        self._xt_timer.stop()
        if self.tex_recipe() is None:
            self.view.set_preview_mesh(None)
            self.xt_stats.setText('')
            return
        self.xt_status.setText('Liczenie podglądu…')
        self._xt_timer.start()

    def _xt_preview(self, force=False):
        recipe = self.tex_recipe()
        if recipe is None or self.mode != 'tex':
            return
        level = self.xt_level.currentData()
        sig = repr((recipe, level)) if not recipe['p'].get('image') else repr((recipe['p'].get('mode'), recipe['p'].get('pattern'), level, id(recipe['p'].get('image')), recipe['p']['image'].get('contrast')))
        sig = (sig, hash(repr({k: v for k, v in recipe['p'].items() if k not in ('image', 'custom_loops')})), len(repr(recipe['p'].get('custom_loops'))), repr(recipe['p'].get('image') and {k: v for k, v in recipe['p']['image'].items() if k != 'data'}))
        self._xt_sig = sig
        bodies = list(self.document.bodies)
        _STATE.update(cancel=False, progress=0.0)

        def compute():
            cancel = lambda: _STATE['cancel']
            if level == 'fast':
                pl = te.plan(bodies, recipe, cancel=cancel)
                return dict(plan=pl, report=pl['report'], count=pl['count'], meshes=_outline_mesh(pl), level=level, stats=dict(count=pl['count']))
            res = te.build(bodies, recipe, cancel=cancel, progress=lambda f: _STATE.update(progress=f), exact=level == 'exact')
            res['level'] = level
            res['count'] = res['plan']['count']
            res['meshes'] = _outline_mesh(res['plan'])
            if level == 'spatial':
                import cadquery as cq
                from .enclosure import merge_meshes
                flat = []
                for t in (res['ups'] + res['downs'])[:1500]:
                    flat += t if isinstance(t, list) else [t]
                res['tool_mesh'] = merge_meshes([kernel.display_mesh(cq.Shape.cast(t)) for t in flat]) if flat else None
            elif res.get('shape') is not None:
                res['result_mesh'] = kernel.display_mesh(res['shape'])
            return res

        def show(value, error):
            self._xt_poll.stop()
            self.xt_bar.setValue(0)
            if self.mode != 'tex' or getattr(self, '_xt_sig', None) != sig:
                return
            if error or value is None:                                    # ostatnia poprawna geometria zostaje
                self.xt_status.setText((str(error) if error else 'Nie udało się.') + ' Model bez zmian.')
                self.xt_apply.setEnabled(False)
                self.view.set_layers_preview([])
                return
            self.xt['result'] = value
            self._xt_show(value)
            ok = bool(value.get('count')) or bool(value['plan']['groups'] and any(g.field is not None for g in value['plan']['groups']))
            self.xt_apply.setEnabled(ok)
            self.xt_status.setText('Enter albo Zastosuj nakłada teksturę.' if ok else 'Żaden element nie mieści się w obszarze.')
        self._xt_poll.start()
        self.run_preview('tex', compute, show)

    def _xt_show(self, value):
        layers = []
        m = value.get('meshes')
        if m is not None:
            layers.append((m, (.2, .5, .95, .2), (.1, .3, .8, 1), 1.2))
        if value.get('tool_mesh') is not None:
            layers.append((value['tool_mesh'], (.95, .55, .15, .5), (.7, .35, .05, 1), 1.0))
        if value.get('result_mesh') is not None:
            layers.append((value['result_mesh'], (.35, .6, .95, .5), (.1, .3, .6, 1), 1.0))
        self.view.set_layers_preview(layers)
        n = int(value.get('count') or 0)
        cx = te.complexity(n, factor=te.surface_factor(self.tex_recipe() or {}))
        st = value.get('stats') or {}
        lines = [f'Przewidywana liczba elementów: {n}', f'Złożoność: {cx["label"]}, szacowany czas operacji ≈ {cx["seconds"]:.1f} s']
        if 'volume_after' in st:
            lines.append(f'Objętość: {st["volume_before"]:.1f} → {st["volume_after"]:.1f} mm³ (zmiana {st["volume_after"] - st["volume_before"]:+.1f}), ścian: {st.get("faces", "-")}')
        if st.get('mesh'):
            lines.append(f'Siatka: {st.get("triangles", 0)} trójkątów (wynik nie jest bryłą B-Rep).')
        if st.get('mass_change') is not None:
            lines.append(f'Zmiana masy: {st["mass_change"]:+.2f} g')
        self.xt_stats.setText('\n'.join(lines))
        self.xt_info.setText('\n'.join(t for _l, t in (value.get('report') or [])[:8]))

    # ------------------------------------------------------------------ reset, konfiguracje
    def tex_reset(self):
        keep = {k: self.xt['p'].get(k) for k in ('pattern', 'mode')}
        self.xt['p'] = dict(copy.deepcopy(tp.DEFAULTS), **keep)
        self.xt.update(region=dict(type='face'), exclusions=[], multi='independent', mapping='auto', cur_grad=-1)
        self._xt_sync()
        self._xt_update()

    def _xt_config(self):
        return dict(p=copy.deepcopy(self.xt['p']), region=copy.deepcopy(self.xt['region']), multi=self.xt['multi'], mapping=self.xt['mapping'])

    def _xt_apply_config(self, cfg):
        self.xt['p'] = dict(copy.deepcopy(tp.DEFAULTS), **(cfg.get('p') or {}))
        self.xt['region'] = dict(cfg.get('region') or {'type': 'face'})
        for k in ('multi', 'mapping'):
            if cfg.get(k):
                self.xt[k] = cfg[k]
        loops = self.xt['p'].get('custom_loops')
        if loops:
            self.xt['p']['custom_loops'] = [np.asarray(q, float) for q in loops]
        self._xt_sync()
        self._xt_update()

    def tex_save_template(self, name=None, category=None):
        if name is None:
            name, ok = QInputDialog.getText(self, 'Zapisz konfigurację tekstury', 'Nazwa konfiguracji:')
            if not ok or not name.strip():
                return
            category, ok = QInputDialog.getText(self, 'Zapisz konfigurację tekstury', 'Kategoria:', text='Moje')
            if not ok:
                category = 'Moje'
        lib.save_template(name.strip(), self._xt_config(), category or 'Moje')
        self._xt_thumbs.pop('tpl:' + name.strip(), None)
        self._xt_gallery_fill()
        self.toast(f'Zapisano konfigurację „{name.strip()}”.')

    def tex_load_template(self):
        from .tex_templates_ui import TemplatesDialog
        dlg = TemplatesDialog(self, lambda cfg: self._xt_apply_config(cfg))
        dlg.exec()
        self._xt_thumbs = {k: v for k, v in self._xt_thumbs.items() if not k.startswith('tpl:')}
        self._xt_gallery_fill()

    def tex_save_file(self, path=None):
        if path is None:
            path, _f = QFileDialog.getSaveFileName(self, 'Zapisz konfigurację tekstury', 'tekstura.json', 'Konfiguracja tekstur (*.json)')
            if not path:
                return
        lib.save_file(path, self._xt_config())
        self.toast('Zapisano konfigurację do pliku.')

    def tex_open_file(self, path=None):
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self, 'Otwórz konfigurację tekstury', '', 'Konfiguracja tekstur (*.json)')
            if not path:
                return
        try:
            self._xt_apply_config(lib.load_file(path))
        except (ValueError, OSError) as exc:
            self.toast(str(exc))

    # ------------------------------------------------------------------ edycja kroku historii
    def _step_fill_tex(self, recipe):
        self.xt.update(target=recipe['target'], faces=[dict(f) for f in recipe['faces']], p=dict(copy.deepcopy(tp.DEFAULTS), **(recipe.get('p') or {})),
                       region=dict(recipe.get('region') or {'type': 'face'}), exclusions=copy.deepcopy(recipe.get('exclusions') or []),
                       multi=recipe.get('multi', 'independent'), mapping=recipe.get('mapping', 'auto'), density=recipe.get('density', 0.0),
                       out_ids=list(recipe.get('out_ids') or []), cur_grad=-1)
        loops = self.xt['p'].get('custom_loops')
        if loops:
            self.xt['p']['custom_loops'] = [np.asarray(q, float) for q in loops]
        self._xt_sync()
        self._xt_update()

    def apply_tex(self):
        if self.busy or self.mode != 'tex' or not self.xt_apply.isEnabled():
            return
        recipe = self.tex_recipe()
        editing = (getattr(self, '_step_edit', None) or {}).get('recipe') or {}
        same = editing.get('type') == 'tex'
        recipe['id'] = editing.get('id') if same and editing.get('id') else uuid.uuid4().hex
        existing = list(self.document.bodies)
        label = 'Tekstury geometryczne'
        preview_only = recipe['p'].get('mode') == 'preview'

        def build_step():
            from .history import run_tex
            return run_tex(existing, recipe)

        def apply(bodies):
            if preview_only:
                return
            self.document.pending_op = recipe
            self.document.pending_label = label
            self.document.pending_icon = 'tex'
            self.document.commit(bodies)

        def after():
            self.view.set_preview_mesh(None)
            self.xt.update(result=None)

        self._xt_timer.stop()
        if preview_only:
            self.toast('Podgląd graficzny - model nie został zmieniony. Wybierz tryb wypukły albo wklęsły, aby nałożyć teksturę.')
            return
        self.view.set_preview_mesh(None)
        self.run_operation(label, build_step, apply, after=after)


# ---------------------------------------------------------------------------------------------- pomocnicze
def su_mapping_labels():
    from . import vent_surface as su
    return su.MAPPING_LABELS


def _outline_mesh(pl):
    """Obrysy elementów odwzorowane na powierzchnię (szybki podgląd): jedna siatka linii."""
    lines = []
    for G in pl['groups']:
        for e in G.elements[:6000]:
            if e.kind == 'poly':
                poly = np.asarray(e.poly, float)
            elif e.kind == 'bar':
                d = np.asarray(e.p1, float) - np.asarray(e.p0, float)
                nn = np.array([-d[1], d[0]]) / max(np.linalg.norm(d), 1e-9) * e.w / 2
                poly = np.array([np.asarray(e.p0) + nn, np.asarray(e.p1) + nn, np.asarray(e.p1) - nn, np.asarray(e.p0) - nn])
            elif e.kind in ('dome', 'solid'):
                t = np.linspace(0, 2 * np.pi, 16, endpoint=False)
                poly = np.asarray(e.c, float) + (e.d or 1.0) / 2 * np.c_[np.cos(t), np.sin(t)]
            else:
                continue
            try:
                pts = []
                for q in np.vstack([poly, poly[:1]]):
                    m, ql = G.locate(q)
                    P, N = m.to3d(ql)[:2]
                    pts.append(np.asarray(P, float) + np.asarray(N, float) * .02)
                lines.append(np.array(pts, np.float32))
            except kernel.CadError:
                continue
    if not lines:
        return None
    allp = np.vstack(lines)
    return kernel.DisplayMesh(allp, np.empty((0, 3), np.uint32), {i: l for i, l in enumerate(lines)}, tuple(map(float, allp.mean(0))),
                              float(np.ptp(allp, axis=0).max()) or 1.0)
