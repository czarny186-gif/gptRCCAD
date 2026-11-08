"""Zakładka Sklejka w oknie programu: Płyta, Ścianka, Półka / przegroda, Połączenia, Do cięcia.

Metody okna (StudioWindow dziedziczy po PlywoodTools). Geometria i rozpoznawanie styków: rccad.plywood,
kroki historii (przeliczane po zmianie wcześniejszych kroków): rccad.history.run_ply_*.
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from . import history as hist
from . import kernel
from . import plywood as pw
from . import shell_ui as ui

PLY_MODES = ('ply', 'ply_wall', 'ply_between', 'ply_joints', 'ply_cut')
PLY_TINT = dict(color=(.87, .69, .45, .62), line_color=(.55, .36, .14, 1), width=2)      # kolor sklejki w podglądzie
DEFAULTS = dict(method='cnc', t={k: v['t'] for k, v in pw.METHODS.items()}, fit={k: v['fit'] for k, v in pw.METHODS.items()},
                tool=6.0, corner='dog', kerf=.15, width=0.0, depth=50, sheet=1200.0, labels=True)


class _Row(QFrame):
    """Wiersz listy połączeń: najechanie podświetla obie płyty w widoku."""
    hovered = Signal(object)

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.setObjectName('plyrow')
        self.setStyleSheet('QFrame#plyrow{background:#f6f9fc;border:1px solid #dbe6f0;border-radius:9px;}'
                           'QFrame#plyrow:hover{background:#eaf3fe;border-color:#9ccbf6;}')

    def enterEvent(self, event):
        self.hovered.emit(self.key)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(None)
        super().leaveEvent(event)


class PlywoodTools:
    # ------------------------------------------------------------------ ustawienia
    def _ply_cfg_load(self):
        cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
        saved = self._read_settings('plywood') or {}
        if isinstance(saved, dict):
            for key, value in saved.items():
                if key in ('t', 'fit') and isinstance(value, dict):
                    cfg[key].update({m: float(v) for m, v in value.items() if m in pw.METHODS and isinstance(v, (int, float))})
                elif key == 'method' and value in pw.METHODS:
                    cfg[key] = value
                elif key in DEFAULTS and isinstance(value, (int, float, bool)) and not isinstance(DEFAULTS[key], dict):
                    cfg[key] = value
        return cfg

    def _ply_cfg_save(self):
        try:
            self._write_settings('plywood', self.ply_cfg)
        except Exception:
            pass

    @property
    def ply_method(self):
        return self.ply_cfg['method']

    def ply_thickness(self):
        return float(self.ply_cfg['t'][self.ply_method])

    # ------------------------------------------------------------------ budowa paneli
    def _ply_common(self, lay):
        """Metoda produkcji i grubość płyty - wspólne dla Płyty, Ścianki i Półki (zmiana w jednym panelu zmienia wszystkie)."""
        from .studio import _label, _spin
        seg = ui.Segmented([(pw.METHODS[m]['short'], m, 'pm_' + m) for m in pw.METHODS], 30)
        for button, m in zip(seg._buttons, seg._data):
            button.setToolTip(pw.METHODS[m]['title'] + ': ' + pw.METHODS[m]['note'])
        self._field(lay, 'Metoda produkcji', seg)
        spin = _spin(self.ply_thickness(), .5, 200, 2, 1)
        spin.setToolTip('Grubość sklejki. Zapamiętywana osobno dla każdej metody produkcji.')
        self._pic_field(lay, 'Grubość płyty (mm)', 'pl_thick', spin, 'Grubość sklejki (płyty).')
        note = _label('', 'help')
        lay.addWidget(note)
        seg.setCurrentIndex(seg.findData(self.ply_method))
        seg.currentIndexChanged.connect(lambda *_, s=seg: self._ply_set_method(s.currentData()))
        spin.valueChanged.connect(lambda value: self._ply_set_thickness(value))
        self._ply_widgets.append((seg, spin, note))
        return seg, spin

    def _ply_sync(self):
        m = self.ply_method
        for seg, spin, note in self._ply_widgets:
            widgets = [w for w in (seg, spin) if w is not None]
            for w in widgets:
                w.blockSignals(True)
            if seg.currentData() != m:
                seg.setCurrentIndex(seg.findData(m))
            if spin is not None and abs(spin.value() - self.ply_thickness()) > 1e-9:
                spin.setValue(self.ply_thickness())
            for w in widgets:
                w.blockSignals(False)
            note.setText(pw.METHODS[m]['note'])
        if hasattr(self, 'pj_tool_box'):
            self.pj_tool_box.setVisible(m == 'cnc')
            self.pc_kerf_box.setVisible(m == 'laser')
            self.pj_fit.blockSignals(True)
            self.pj_fit.setValue(float(self.ply_cfg['fit'][m]))
            self.pj_fit.blockSignals(False)

    def _ply_set_method(self, m):
        if m not in pw.METHODS or m == self.ply_method:
            return
        self.ply_cfg['method'] = m
        self._ply_cfg_save()
        self._ply_sync()
        if self.mode == 'ply_joints':
            self._pj_method_changed()
        elif self.mode == 'ply_cut':
            self._pc_update()
        else:
            self._ply_update()

    def _ply_set_thickness(self, value):
        self.ply_cfg['t'][self.ply_method] = float(value)
        self._ply_cfg_save()
        self._ply_sync()
        self._ply_update()

    def _build_ply_panels(self):
        from .studio import _label, _spin
        self.ply_cfg = self._ply_cfg_load()
        self._ply_widgets = []
        self.ply_profiles = []
        self.pw_base, self.pw_edges = None, []
        self.pb_faces = []
        self.pj_contacts, self.pj_rows, self.pj_skipped = [], {}, []

        # --- Płyta ze szkicu ---
        self.ply_panel, lay = self._panel(312, 'Płyta', 'x_ply', 'Szkic albo ściana → płyta ze sklejki', plain=True, scroll=True)
        self.ply_step1 = ui.StepRow(1, 'x_object', 'Profil szkicu albo ściana', plain=True)
        lay.addWidget(self.ply_step1)
        self._ply_common(lay)
        self.ply_side = ui.Segmented([('Nad szkicem', 'up', 'pl_up'), ('Pod szkicem', 'down', 'pl_down')], 30)
        self._field(lay, 'Strona płyty', self.ply_side)
        self.ply_status = _label('Kliknij zamknięty profil szkicu (dowolny kształt) albo płaską ścianę. Shift + klik dodaje kolejne.', 'status')
        lay.addWidget(self.ply_status)
        self._buttons(self.ply_panel.footer, 'Zastosuj', 'Zamknij', self.apply_ply_panel, lambda: self.set_mode(None))
        self.ply_side.currentIndexChanged.connect(lambda *_: self._ply_update())

        # --- Ścianka na krawędzi ---
        self.ply_wall_panel, lay = self._panel(312, 'Ścianka', 'x_plywall', 'Płyta na krawędzi płyty', plain=True, scroll=True)
        self.pw_step1 = ui.StepRow(1, 'x_object', 'Krawędź płyty', plain=True)
        lay.addWidget(self.pw_step1)
        self._ply_common(lay)
        self.pw_height = _spin(80, 1, 1e5, 2, 5)
        self.pw_height.setToolTip('Wysokość ścianki od płyty-podstawy; można też przeciągać strzałkę w widoku.')
        self._pic_field(lay, 'Wysokość (mm)', 'pw_height', self.pw_height, 'Wysokość ścianki ponad podstawą.')
        self.pw_side = ui.Segmented([('Na podstawie', 'on', 'pw_on'), ('Przy boku', 'side', 'pw_side')], 30)
        self.pw_side._buttons[0].setToolTip('Ścianka stoi na podstawie i licuje z jej krawędzią.')
        self.pw_side._buttons[1].setToolTip('Ścianka stoi obok podstawy i zakrywa jej brzeg.')
        self._field(lay, 'Ustawienie', self.pw_side)
        self.pw_flip = QCheckBox('Po drugiej stronie płyty')
        lay.addWidget(self.pw_flip)
        self.pw_status = _label('Kliknij prostą krawędź płaskiej strony płyty. Shift + klik dodaje kolejne krawędzie.', 'status')
        lay.addWidget(self.pw_status)
        self._buttons(self.ply_wall_panel.footer, 'Zastosuj', 'Zamknij', self.apply_ply_wall, lambda: self.set_mode(None))
        self.pw_height.valueChanged.connect(lambda *_: self._ply_update())
        self.pw_side.currentIndexChanged.connect(lambda *_: self._ply_update())
        self.pw_flip.toggled.connect(lambda *_: self._ply_update())

        # --- Półka / przegroda między ścianami ---
        self.ply_between_panel, lay = self._panel(312, 'Półka / przegroda', 'x_plybetween', 'Płyta między dwiema ścianami', plain=True, scroll=True)
        self.pb_step1 = ui.StepRow(1, 'x_object', 'Pierwsza ściana', plain=True)
        self.pb_step2 = ui.StepRow(2, 'x_object', 'Druga ściana (naprzeciw)', plain=True)
        lay.addWidget(self.pb_step1)
        lay.addWidget(self.pb_step2)
        self._ply_common(lay)
        self.pb_turn = ui.Segmented([('Pozioma', 'h', 'pb_h'), ('Pionowa', 'v', 'pb_v')], 30)
        self._field(lay, 'Płyta', self.pb_turn)
        self.pb_count = _spin(1, 1, 50, 0, 1)
        self.pb_count.setToolTip('Więcej niż jedna: płyty rozłożone równo w całym wspólnym obszarze ścian.')
        self._pic_field(lay, 'Liczba płyt', 'pb_count', self.pb_count, 'Liczba półek / przegród rozłożonych równo.')
        self.pb_pos = _spin(0, 0, 1e5, 2, 5)
        self.pb_pos.setToolTip('Odległość płyty od dolnego brzegu wspólnego obszaru ścian; można też przeciągać strzałkę.')
        self._pic_field(lay, 'Położenie od dołu (mm)', 'pb_pos', self.pb_pos, 'Położenie półki.')
        self.pb_status = _label('Kliknij ścianę (np. wewnętrzną stronę boku szafki), potem ścianę naprzeciw.', 'status')
        lay.addWidget(self.pb_status)
        self._buttons(self.ply_between_panel.footer, 'Zastosuj', 'Zamknij', self.apply_ply_between, lambda: self.set_mode(None))
        self.pb_turn.currentIndexChanged.connect(lambda *_: self._pb_reset_pos())
        self.pb_count.valueChanged.connect(lambda *_: self._ply_update())
        self.pb_pos.valueChanged.connect(lambda *_: self._ply_update())

        # --- Połączenia ---
        self.ply_joints_panel, lay = self._panel(340, 'Połączenia', 'x_plyjoints', 'Wczepy, czopy, rowki, nacięcia', plain=True, scroll=True)
        self.pj_method = ui.Segmented([(pw.METHODS[m]['short'], m, 'pm_' + m) for m in pw.METHODS], 30)
        self._field(lay, 'Metoda produkcji', self.pj_method)
        note = _label('', 'help')
        lay.addWidget(note)
        self._ply_widgets.append((self.pj_method, None, note))
        self.pj_method.currentIndexChanged.connect(lambda *_: self._ply_set_method(self.pj_method.currentData()))
        self.pj_width = _spin(float(self.ply_cfg['width']), 0, 1e4, 1, 1)
        self.pj_width.setToolTip('Szerokość jednego noska / czopa; 0 - sama (około 3 grubości płyty), liczba nosków zawsze nieparzysta.')
        self._pic_field(lay, 'Szerokość noska (mm, 0 = sama)', 'pj_width', self.pj_width, 'Szerokość noska / czopa.')
        self.pj_fit = _spin(float(self.ply_cfg['fit'][self.ply_method]), 0, 5, 2, .05)
        self.pj_fit.setToolTip('Gniazda i nacięcia większe o tyle - 0 na wcisk, więcej luźniej.')
        self._pic_field(lay, 'Luz pasowania (mm)', 'pj_fit', self.pj_fit, 'Luz między czopem a gniazdem.')
        self.pj_tool_box = QWidget()
        box = QVBoxLayout(self.pj_tool_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.pj_tool = _spin(float(self.ply_cfg['tool']), 0, 50, 2, .5)
        self.pj_tool.setToolTip('Frez nie zrobi ostrego kąta wewnętrznego - narożniki gniazd i wczepów dostają „psie kości” na ten promień. 0 - bez.')
        self._pic_field(box, 'Średnica frezu (mm)', 'pj_tool', self.pj_tool, 'Wycięcia na frez w narożnikach gniazd i nosków.')
        self.pj_corner = ui.Segmented([(pw.CORNERS[k][0], k, 'pd_' + k) for k in pw.CORNERS], 30)
        self.pj_corner.setCurrentIndex(max(0, list(pw.CORNERS).index(self.ply_cfg.get('corner', 'dog')) if self.ply_cfg.get('corner', 'dog') in pw.CORNERS else 0))
        for k, button in zip(pw.CORNERS, self.pj_corner._buttons):
            button.setToolTip(pw.CORNERS[k][1])
        self._field(box, 'Narożniki gniazd i nosków', self.pj_corner)
        self.pj_corner_note = _label(pw.CORNERS[self.pj_corner.currentData()][1], 'help')
        box.addWidget(self.pj_corner_note)
        self.pj_tool_warn = _label('', 'status')
        self.pj_tool_warn.setStyleSheet('color:#c0392b;')
        self.pj_tool_warn.setWordWrap(True)
        box.addWidget(self.pj_tool_warn)
        self.pj_tool_fix = QPushButton('Dobierz frez')
        self.pj_tool_fix.setToolTip('Ustaw największy typowy frez, który mieści się w gniazdach.')
        self.pj_tool_fix.clicked.connect(self._pj_fix_tool)
        box.addWidget(self.pj_tool_fix)
        lay.addWidget(self.pj_tool_box)
        self.pj_depth = _spin(int(self.ply_cfg['depth']), 10, 90, 0, 5)
        self.pj_depth.setToolTip('Głębokość gniazd nieprzelotowych i rowków jako część grubości płyty, w którą wchodzą.')
        self._pic_field(lay, 'Głębokość gniazda / rowka (% grubości)', 'pj_depth', self.pj_depth, 'Głębokość gniazd nieprzelotowych i rowków.')
        lay.addWidget(_label('Połączenia (najedź, żeby zobaczyć płyty):'))
        self.pj_list = QWidget()
        self.pj_list_lay = QVBoxLayout(self.pj_list)
        self.pj_list_lay.setContentsMargins(0, 0, 0, 0)
        self.pj_list_lay.setSpacing(6)
        lay.addWidget(self.pj_list)
        self.pj_status = _label('', 'status')
        lay.addWidget(self.pj_status)
        self._buttons(self.ply_joints_panel.footer, 'Zastosuj', 'Zamknij', self.apply_ply_joints, lambda: self.set_mode(None))
        for w in (self.pj_width, self.pj_fit, self.pj_tool):
            w.valueChanged.connect(lambda *_: self._pj_params_changed())
        self.pj_depth.valueChanged.connect(lambda *_: self._pj_params_changed())
        self.pj_corner.currentIndexChanged.connect(lambda *_: self._pj_params_changed())

        # --- Do cięcia ---
        self.ply_cut_panel, lay = self._panel(340, 'Do cięcia', 'x_plycut', 'Lista płyt i plik do lasera, frezarki, drukarki', plain=True, scroll=True)
        self.pc_method = ui.Segmented([(pw.METHODS[m]['short'], m, 'pm_' + m) for m in pw.METHODS], 30)
        self._field(lay, 'Metoda produkcji', self.pc_method)
        note = _label('', 'help')
        lay.addWidget(note)
        self._ply_widgets.append((self.pc_method, None, note))
        self.pc_method.currentIndexChanged.connect(lambda *_: self._ply_set_method(self.pc_method.currentData()))
        self.pc_scope = ui.Segmented([('Wszystkie płyty', 'all', 'pc_all'), ('Zaznaczone', 'sel', 'pc_sel')], 30)
        self.pc_scope._buttons[0].setToolTip('Wszystkie widoczne płyty ze sklejki.')
        self.pc_scope._buttons[1].setToolTip('Tylko płyty zaznaczone na polu roboczym albo na liście obiektów.')
        self._field(lay, 'Zapisz', self.pc_scope)
        self.pc_scope.currentIndexChanged.connect(lambda *_: self._pc_update())
        self.pc_list = QLabel('—')
        self.pc_list.setObjectName('readout')
        self.pc_list.setWordWrap(True)
        self.pc_list.setTextFormat(Qt.RichText)
        self.pc_list.setStyleSheet('QLabel#readout{background:#f3f6fa;border:1.4px solid #d6e0ea;border-radius:8px;padding:7px 10px;color:#27415a;}')
        self._field(lay, 'Lista płyt', self.pc_list)
        self.pc_sheet = _spin(float(self.ply_cfg['sheet']), 100, 1e5, 0, 50)
        self.pc_sheet.setToolTip('Płyty układane w rzędach nie szerszych niż ta wartość (z odstępem 10 mm).')
        self._pic_field(lay, 'Szerokość ułożenia (mm)', 'pc_sheet', self.pc_sheet, 'Szerokość, w której płyty są układane w pliku.')
        self.pc_kerf_box = QWidget()
        box = QVBoxLayout(self.pc_kerf_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.pc_kerf = _spin(float(self.ply_cfg['kerf']), 0, 2, 2, .05)
        self.pc_kerf.setToolTip('Obrysy w pliku przesunięte o połowę szerokości cięcia (na zewnątrz, otwory do środka) - wymiary po cięciu się zgadzają. 0 - bez kompensacji.')
        self._pic_field(box, 'Szerokość cięcia lasera (mm)', 'pc_kerf', self.pc_kerf, 'Kompensacja szerokości wiązki.')
        lay.addWidget(self.pc_kerf_box)
        self.pc_labels = QCheckBox('Nazwy płyt w pliku (osobna warstwa OPIS)')
        self.pc_labels.setChecked(bool(self.ply_cfg['labels']))
        lay.addWidget(self.pc_labels)
        self.pc_status = _label('', 'status')
        lay.addWidget(self.pc_status)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.pc_export = QPushButton('Zapisz DXF…')
        self.pc_export.setObjectName('primary')
        self.pc_export.clicked.connect(lambda _=False: self.ply_export())
        close = QPushButton('Zamknij')
        close.clicked.connect(lambda _=False: self.set_mode(None))
        row.addWidget(self.pc_export)
        row.addWidget(close)
        self.ply_cut_panel.footer.addLayout(row)
        for w in (self.pc_sheet, self.pc_kerf):
            w.valueChanged.connect(lambda *_: self._pc_params_changed())
        self.pc_labels.toggled.connect(lambda *_: self._pc_params_changed())
        self._ply_sync()

    def ply_panels(self):
        return (self.ply_panel, self.ply_wall_panel, self.ply_between_panel, self.ply_joints_panel, self.ply_cut_panel)

    # ------------------------------------------------------------------ tryby
    def _ply_enter(self, mode):
        panel = {'ply': self.ply_panel, 'ply_wall': self.ply_wall_panel, 'ply_between': self.ply_between_panel,
                 'ply_joints': self.ply_joints_panel, 'ply_cut': self.ply_cut_panel}[mode]
        panel.show()
        self.ply_profiles, self.pw_base, self.pw_edges, self.pb_faces = [], None, [], []
        self._ply_sync()
        from PySide6.QtCore import Qt as _Qt
        self.view.setCursor(_Qt.PointingHandCursor)
        if mode == 'ply_joints':
            self._pj_detect()
        elif mode == 'ply_cut':
            self._pc_update()
        else:
            self._ply_update()

    def ply_clicked(self, x, y, shift):
        if self.mode == 'ply':
            self._ply_pick_profile(x, y, shift)
        elif self.mode == 'ply_wall':
            self._pw_pick(x, y, shift)
        elif self.mode == 'ply_between':
            self._pb_pick(x, y)
        elif self.mode in ('ply_joints', 'ply_cut'):
            bid = self.view.pick_body(x, y)
            body = self.document.get(bid) if bid else None
            if body is not None and pw.is_panel(body):
                if self.mode == 'ply_cut' and shift:
                    ids = [i for i in self.selected if i != body.id] if body.id in self.selected else [*self.selected, body.id]
                    self._tool_select(ids)
                else:
                    self._tool_select([body.id])
                if self.mode == 'ply_cut':
                    self._pc_update()
                if self.mode == 'ply_joints':
                    self._pj_hover(next((c['key'] for c in self.pj_contacts if body.id in (c['a'], c['b'])), None))

    def ply_hover(self, x, y):
        if self.mode == 'ply' and not self.ply_profiles:
            self._hover_extrude(x, y)
        elif self.mode == 'ply_wall':
            self.view._set_hover_edge(self.view.nearest_edge(x, y, True))
        elif self.mode == 'ply_between' and len(self.pb_faces) < 2:
            self._hover_face_only(x, y)

    # ------------------------------------------------------------------ Płyta ze szkicu
    def _ply_pick_profile(self, x, y, shift):
        try:
            src = self._profile_at(x, y)
        except Exception as exc:
            self.toast(str(exc) or 'Nie udało się wybrać profilu.')
            return
        if src is None or src.get('kind') == 'cyl':
            self.toast('Kliknij zamknięty profil szkicu albo płaską ścianę bryły.')
            return
        group = [src, *src.get('siblings', ())]
        same = lambda p: p['id'] == src['id'] and p['kind'] == src['kind'] and np.allclose(p['center'], src['center'], atol=1e-6)
        if shift:
            dup = [p for p in self.ply_profiles if same(p)]
            self.ply_profiles = [p for p in self.ply_profiles if p not in dup] if dup else [*self.ply_profiles, *group]
        else:
            self.ply_profiles = group
        self._hover_key = None
        self.view.set_preview_mesh(None)
        self._ply_update()

    def _ply_makers(self):
        d = self.ply_thickness() * (1 if self.ply_side.currentData() == 'up' else -1)
        return [(lambda src=src: hist.make_tool(src, d, 0.0, 'one')) for src in self.ply_profiles], d

    # ------------------------------------------------------------------ Ścianka
    def _pw_pick(self, x, y, shift):
        hit = self.view.nearest_edge(x, y, True)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij prostą krawędź płyty.')
            return
        edge = body.shape.Edges()[hit[1]]
        try:
            pw.edge_wall(body.shape, edge, self.ply_thickness(), 10, 'on', False, (body.meta or {}).get('ply', {}).get('t'))
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        if body.id != self.pw_base or not shift:
            self.pw_base, self.pw_edges = body.id, [hit[1]]
        elif hit[1] in self.pw_edges:
            self.pw_edges = [i for i in self.pw_edges if i != hit[1]]
        else:
            self.pw_edges = [*self.pw_edges, hit[1]]
        self.view._set_hover_edge(None)
        self._ply_update()

    def _pw_recipe(self):
        base = self.document.get(self.pw_base) if self.pw_base else None
        if base is None or not self.pw_edges:
            return None, None
        return base, dict(type='ply_wall', base=base.id, t=self.ply_thickness(), h=float(self.pw_height.value()), side=self.pw_side.currentData(),
                          flip=bool(self.pw_flip.isChecked()), method=self.ply_method, ignore=self._ply_hidden())

    # ------------------------------------------------------------------ Półka / przegroda
    def _pb_pick(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij płaską ścianę bryły albo płyty.')
            return
        try:
            face, normal = kernel.face_at(body.shape, hit[1], hit[2])
        except kernel.CadError:
            self.toast('Kliknij płaską ścianę.')
            return
        entry = dict(id=body.id, face=face, normal=np.array(normal, float), point=np.array(hit[2], float), name=body.name)
        if len(self.pb_faces) >= 2:
            self.pb_faces = []
        if self.pb_faces:
            first = self.pb_faces[0]
            gap = float((entry['point'] - first['point']) @ first['normal'])
            if abs(float(first['normal'] @ entry['normal']) + 1) > 1e-3 or gap <= 1e-3:
                self.toast('Druga ściana musi być równoległa i zwrócona do pierwszej (naprzeciw niej).')
                return
        self.pb_faces = [*self.pb_faces, entry]
        self._hover_key = None
        self.view.set_preview_mesh(None)
        if len(self.pb_faces) == 2:
            self._pb_reset_pos()
        else:
            self._ply_update()

    def _ply_hidden(self):
        """Płyty ukryte na liście obiektów (przekreślone oko): nowe płyty ich nie widzą - nie docinają się do nich."""
        hidden = self.shown_hidden() if hasattr(self, 'shown_hidden') else set()
        return sorted(b.id for b in self.document.bodies if b.id in hidden and pw.is_panel(b))

    def _pb_recipe(self):
        if len(self.pb_faces) < 2:
            return None
        refs = []
        for f in self.pb_faces:
            body = self.document.get(f['id'])
            refs.append(dict(hist.face_ref(f['face'], f['normal'], f['point'], body.shape if body else None), id=f['id']))
        count = int(round(self.pb_count.value()))
        return dict(type='ply_between', a=refs[0], b=refs[1], t=self.ply_thickness(), pos=None if count > 1 else float(self.pb_pos.value()),
                    count=count, turn=self.pb_turn.currentData() == 'v', method=self.ply_method, ignore=self._ply_hidden(),
                    fit=float(self.ply_cfg['fit'][self.ply_method]), **self._ply_tool_args())

    def _ply_tool_args(self):
        """Frez i rodzaj narożników z panelu Połączenia (nacięcia krzyżowe nowych przegród frezowanych tym samym frezem)."""
        if self.ply_method != 'cnc':
            return dict(tool=0.0, corner='dog')
        return dict(tool=float(self.ply_cfg.get('tool', 6.0)), corner=self.ply_cfg.get('corner', 'dog'))

    def _pb_reset_pos(self):
        """Nowe ściany albo inny kierunek płyty: położenie na środku wspólnego obszaru."""
        if len(self.pb_faces) == 2:
            a, b = self.pb_faces
            try:
                _, info = pw.between_panels(a['face'], a['point'], a['normal'], b['face'], b['point'], self.ply_thickness(), None, 1,
                                            self.pb_turn.currentData() == 'v')
                self.pb_pos.blockSignals(True)
                self.pb_pos.setValue(round((info['span'] - self.ply_thickness()) / 2, 2))
                self.pb_pos.blockSignals(False)
            except kernel.CadError:
                pass
        self._ply_update()

    # ------------------------------------------------------------------ podgląd Płyty / Ścianki / Półki
    def _ply_update(self):
        """Podgląd na żywo (kolor sklejki) i strzałki - same prostopadłościany / wyciągnięcia, liczone od razu."""
        if self.mode not in ('ply', 'ply_wall', 'ply_between'):
            return
        shapes, handles, status = [], [], None
        try:
            if self.mode == 'ply':
                n = len(self.ply_profiles)
                self.ply_step1.set_state('done' if n else 'active', f'Wybrane profile: {n}' if n else 'Kliknij profil albo ścianę')
                if n:
                    makers, _ = self._ply_makers()
                    shapes = [m() for m in makers]
                    self.view.set_selection_meshes([kernel.display_mesh(p.get('face') or hist.profile_face(p['wire'])) for p in self.ply_profiles])
                    status = f'Płyty: {n} × {self.ply_thickness():g} mm. Zastosuj albo Enter tworzy płyty.'
            elif self.mode == 'ply_wall':
                base, recipe = self._pw_recipe()
                if base is None:
                    self.pw_step1.set_state('active', 'Kliknij krawędź płyty')
                else:
                    self.pw_step1.set_state('done', f'{base.name} · krawędzie: {len(self.pw_edges)}')
                    shapes = hist.ply_walls(list(self.document.bodies), base, self.pw_edges, recipe)
                    up = pw.edge_wall(base.shape, base.shape.Edges()[self.pw_edges[0]], recipe['t'], recipe['h'], recipe['side'], recipe['flip'],
                                      (base.meta or {}).get('ply', {}).get('t'))[1]
                    top = shapes[0].Center().toTuple() if shapes else None
                    if top is not None:
                        c = np.array(top, float)
                        lo, hi = pw.extent(shapes[0], up)
                        start = c + up * (hi - float(c @ up))
                        handles.append(dict(id='plyH', start=start, tip=start + up * max(15.0, recipe['h'] * .35), dir=up, color=(.94, .6, .13, 1)))
                    status = f"Ścianki: {len(shapes)} × {recipe['h']:g} mm. Przeciągnij strzałkę albo wpisz wysokość."
            else:
                self.pb_step1.set_state('done' if self.pb_faces else 'active', self.pb_faces[0]['name'] if self.pb_faces else 'Kliknij ścianę')
                self.pb_step2.set_state('done' if len(self.pb_faces) > 1 else ('active' if self.pb_faces else 'pending'),
                                        self.pb_faces[1]['name'] if len(self.pb_faces) > 1 else 'Kliknij ścianę naprzeciw')
                self.pb_pos.setEnabled(int(round(self.pb_count.value())) == 1)
                self.view.set_selection_meshes([kernel.display_mesh(f['face']) for f in self.pb_faces] or None)
                recipe = self._pb_recipe()
                if recipe is not None:
                    a, b = self.pb_faces
                    shapes, info = pw.between_panels(a['face'], a['point'], a['normal'], b['face'], b['point'], recipe['t'], recipe['pos'],
                                                     recipe['count'], recipe['turn'])
                    shapes, changed, joined = hist.ply_between_fit(list(self.document.bodies), shapes, recipe)
                    crossed = sum(len(v) for v in joined.values())
                    shapes = [*shapes, *changed.values()]      # także nacięte istniejące płyty (nacięcia krzyżowe)
                    if recipe['count'] == 1:
                        s = np.array(info['s'], float)
                        start = info['centre'] + s * (info['starts'][0] + recipe['t'])
                        handles.append(dict(id='plyP', start=start, tip=start + s * max(15.0, info['span'] * .2), dir=s, color=(.94, .6, .13, 1)))
                    lo, hi = pw.extent(shapes[0], info['w']) if shapes else (0.0, info['depth'])
                    status = (f"{recipe['count']} × {recipe['t']:g} mm, szerokość {info['gap']:.1f}, głębokość {hi - lo:.1f} mm. "
                              + (f'Nacięcia krzyżowe z istniejącymi płytami: {crossed}. ' if crossed else '') + 'Strzałka przesuwa płytę.')
        except kernel.CadError as exc:
            shapes, status = [], str(exc)
        except Exception as exc:
            shapes, status = [], f'Podgląd niedostępny: {exc}'
        label = {'ply': self.ply_status, 'ply_wall': self.pw_status, 'ply_between': self.pb_status}[self.mode]
        if status:
            label.setText(status)
        if shapes:
            compound = shapes[0] if len(shapes) == 1 else kernel.compound(shapes)
            self.view.set_preview_mesh(kernel.display_mesh(compound, .3), **PLY_TINT)
        elif self.mode != 'ply' or self.ply_profiles:
            self.view.set_preview_mesh(None)
        self.view.set_handles(handles)

    def ply_handle_dragged(self, hid, delta):
        if hid == 'plyH':
            if self._hv is None:
                self._hv = self.pw_height.value()
            self.pw_height.setValue(max(1.0, round(self._hv + delta, 1)))
        elif hid == 'plyP':
            if self._hv is None:
                self._hv = self.pb_pos.value()
            self.pb_pos.setValue(max(0.0, round(self._hv + delta, 1)))

    # ------------------------------------------------------------------ zastosowanie: Płyta, Ścianka, Półka
    def apply_ply_panel(self):
        if self.busy or not self.ply_profiles:
            self.toast('Kliknij profil szkicu albo ścianę.')
            return
        existing = list(self.document.bodies)
        profiles = list(self.ply_profiles)
        spent = sorted(self._consumed_sketches(profiles))
        _, d = self._ply_makers()
        out = [uuid.uuid4().hex for _ in profiles]
        meth, t = self.ply_method, self.ply_thickness()

        def build():
            recipe = dict(type='ply_panel', profiles=hist.describe_profiles(profiles, existing), d=d, t=t, method=meth, spent=spent, out=out)
            return hist.offloaded(hist.run_ply_panel, existing, recipe), recipe

        self._ply_run('Płyta', build)

    def apply_ply_wall(self):
        base, recipe = self._pw_recipe()
        if self.busy or recipe is None:
            self.toast('Kliknij krawędź płyty.')
            return
        recipe.update(edges=hist.edge_refs(base.shape, self.pw_edges), out=[uuid.uuid4().hex for _ in self.pw_edges])
        existing = list(self.document.bodies)

        def build():
            return hist.offloaded(hist.run_ply_wall, existing, recipe), recipe

        self._ply_run('Ścianka', build)

    def apply_ply_between(self):
        recipe = self._pb_recipe()
        if self.busy or recipe is None:
            self.toast('Kliknij dwie ściany naprzeciw siebie.')
            return
        recipe['out'] = [uuid.uuid4().hex for _ in range(recipe['count'])]
        existing = list(self.document.bodies)

        def build():
            return hist.offloaded(hist.run_ply_between, existing, recipe), recipe

        self._ply_run('Przegroda' if recipe['turn'] else 'Półka', build)

    def _ply_run(self, label, build):
        mode = self.mode

        def apply(result):
            bodies, recipe = result
            self.document.pending_op = recipe
            self.document.pending_label, self.document.pending_icon = label, mode
            before = {b.id for b in self.document.bodies}
            self.document.commit(bodies)
            self._tool_select([b.id for b in bodies if b.id not in before])

        self.view.set_preview_mesh(None)
        self.view.set_selection_meshes(None)
        self.view.set_handles([])

        def again():
            if self.mode == mode:
                self.ply_profiles, self.pw_base, self.pw_edges, self.pb_faces = [], None, [], []
                self._ply_update()

        self.run_operation(label, build, apply, after=again)

    # ------------------------------------------------------------------ Połączenia
    def _pj_detect(self):
        """Styki płyt liczone w procesie w tle - okno od razu działa, lista połączeń pojawia się po chwili."""
        hidden = set(self._ply_hidden())
        ids = [b.id for b in self.document.bodies if pw.is_panel(b) and b.visible and b.id not in hidden]   # ukryte - bez połączeń
        self.pj_contacts, self.pj_skipped, self.pj_ids, self.pj_failed = [], [], ids, {}
        self._pj_build_rows()
        self.pj_status.setText('Szukam miejsc, w których płyty się stykają…' if ids else '')
        if not ids:
            return
        existing = hist.light(self.document.bodies)

        def compute():
            return hist.background(hist.ply_detect_job, existing, ids)

        def show(value, error):
            if self.mode != 'ply_joints':
                return
            if error:
                self.pj_status.setText(str(error))
                return
            found_ids, names, methods, contacts, skipped = value
            counts = {}
            for m in methods.values():
                counts[m] = counts.get(m, 0) + 1
            if counts:
                common = max(counts, key=counts.get)
                if common != self.ply_method and common in pw.METHODS:
                    self.ply_cfg['method'] = common
                    self._ply_sync()
            for c in contacts:
                c['joint'] = pw.joint_for(self.ply_method, c['kind'])
                c['title'] = f"{pw.KIND_TITLES[c['kind']]}: {names.get(c['a'], '?')} ↔ {names.get(c['b'], '?')}"
            self.pj_contacts, self.pj_skipped, self.pj_ids = contacts, skipped, found_ids
            self._pj_build_rows()
            self._pj_params_changed(save=False)

        self.run_preview('ply_detect', compute, show)

    def _pj_build_rows(self):
        while self.pj_list_lay.count():
            item = self.pj_list_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.pj_rows = {}
        for c in self.pj_contacts:
            row = _Row(c['key'])
            lay = QVBoxLayout(row)
            lay.setContentsMargins(9, 7, 9, 8)
            lay.setSpacing(5)
            title = QLabel(c['title'])
            title.setWordWrap(True)
            title.setStyleSheet('font-weight:700;color:#1e3a52;background:transparent;')
            combo = QComboBox()
            self._pj_fill_combo(combo, c)
            combo.currentIndexChanged.connect(lambda *_, key=c['key'], cb=combo: self._pj_joint_changed(key, cb.currentData()))
            lay.addWidget(title)
            if c['kind'] == 'M':
                note = QLabel(f"Narożnik {180 - c.get('angle', 90):g}°. Laser i frezarka: końce cięte prostopadle, ścianki na przemian "
                              'dochodzą do narożnika (druga cofnięta). Druk 3D: wczepy na skos.')
                note.setWordWrap(True)
                note.setStyleSheet('color:#6b7d90;font-size:11px;background:transparent;')
                lay.addWidget(note)
            lay.addWidget(combo)
            row.hovered.connect(self._pj_hover)
            self.pj_list_lay.addWidget(row)
            self.pj_rows[c['key']] = (row, combo)
        if not self.pj_contacts:
            empty = QLabel('Brak stykających się płyt. Płyty powstają w narzędziach Płyta, Ścianka i Półka.')
            empty.setWordWrap(True)
            empty.setObjectName('help')
            self.pj_list_lay.addWidget(empty)

    def _pj_fill_combo(self, combo, c):
        combo.blockSignals(True)
        combo.clear()
        model = combo.model()
        for j in pw.KIND_JOINTS[c['kind']]:
            combo.addItem(pw.JOINTS[j][0], j)
            index = combo.count() - 1
            ok = pw.allowed(self.ply_method, j)
            if isinstance(model, QStandardItemModel):
                model.item(index).setEnabled(ok)
            combo.setItemData(index, pw.JOINTS[j][1] if ok else f"Niedostępne: {pw.WHY_NOT.get(self.ply_method, '')}", Qt.ToolTipRole)
        combo.setCurrentIndex(combo.findData(c['joint']))
        combo.blockSignals(False)

    def _pj_joint_changed(self, key, joint):
        for c in self.pj_contacts:
            if c['key'] == key:
                c['joint'] = joint
        self._pj_params_changed(save=False)

    def _pj_method_changed(self):
        """Inna metoda: połączenia, których nie da się nią wykonać, zamieniają się na możliwe odpowiedniki."""
        changed = []
        for c in self.pj_contacts:
            new = pw.joint_for(self.ply_method, c['kind'], c['joint'])
            if new != c['joint']:
                changed.append(f"{pw.JOINTS[c['joint']][0]} → {pw.JOINTS[new][0]}")
                c['joint'] = new
            row = self.pj_rows.get(c['key'])
            if row:
                self._pj_fill_combo(row[1], c)
        if changed:
            self.toast(f"{pw.METHODS[self.ply_method]['title']}: zmienione połączenia ({len(changed)}): " + ', '.join(sorted(set(changed))), 6000)
        self._pj_params_changed(save=False)

    def _pj_params(self):
        return dict(method=self.ply_method, width=float(self.pj_width.value()), fit=float(self.pj_fit.value()),
                    tool=float(self.pj_tool.value()) if self.ply_method == 'cnc' else 0.0, depth=float(self.pj_depth.value()) / 100.0,
                    corner=self.pj_corner.currentData())

    def _pj_thickness(self):
        """Najcieńsza płyta wśród wykrytych styków (bez styków - grubość z ustawień metody)."""
        ts = [float(c[k]) for c in self.pj_contacts for k in ('ta', 'tb') if c.get(k)]
        return min(ts) if ts else float(self.ply_thickness())

    def _pj_tool_state(self):
        """Ostrzeżenie, gdy frez nie mieści się w gniazdach, i przycisk z dobranym frezem."""
        if not hasattr(self, 'pj_tool_warn'):
            return
        cnc = self.ply_method == 'cnc'
        msg, fits = pw.tool_check(self._pj_thickness(), self.pj_fit.value(), self.pj_tool.value(), self.pj_width.value()) if cnc else ('', 0)
        self.pj_tool_warn.setText(msg)
        self.pj_tool_warn.setVisible(bool(msg))
        self.pj_tool_fix.setVisible(bool(msg) and fits > 0)
        if fits:
            self.pj_tool_fix.setText(f'Dobierz frez Ø{fits:g} mm')
        self.pj_corner_note.setText(pw.CORNERS[self.pj_corner.currentData()][1])

    def _pj_fix_tool(self):
        _msg, fits = pw.tool_check(self._pj_thickness(), self.pj_fit.value(), self.pj_tool.value(), self.pj_width.value())
        if fits:
            self.pj_tool.setValue(fits)

    def _pj_params_changed(self, save=True):
        if save:
            self.ply_cfg.update(width=float(self.pj_width.value()), tool=float(self.pj_tool.value()), depth=int(round(self.pj_depth.value())),
                                corner=self.pj_corner.currentData())
            self.ply_cfg['fit'][self.ply_method] = float(self.pj_fit.value())
            self._ply_cfg_save()
        self._pj_tool_state()
        active = sum(1 for c in self.pj_contacts if c['joint'] != 'none')
        text = f'Styków: {len(self.pj_contacts)}, połączeń do wykonania: {active}.'
        if self.pj_skipped:
            text += ' Pominięte: ' + '; '.join(sorted({m for *_, m in self.pj_skipped}))
        self.pj_status.setText(text)
        timer = getattr(self, '_timers', {}).get('ply_joints')
        if timer is not None:
            timer.start()

    def _pj_hover(self, key):
        c = next((c for c in self.pj_contacts if c['key'] == key), None) if key else None
        meshes = []
        if c is not None:
            for bid in (c['a'], c['b']):
                body = self.override.get(bid) or self.document.get(bid)
                if body is not None and body.mesh is not None:
                    meshes.append(body.mesh)
        self.view.set_selection_meshes(meshes or None, color=(1, .55, .1, .4), line_color=(.95, .42, .02, 1))

    def _pj_recipe(self):
        if not self.pj_contacts:
            return None
        return dict(type='ply_joints', ids=list(self.pj_ids), joints={c['key']: c['joint'] for c in self.pj_contacts}, params=self._pj_params())

    def update_ply_joints_preview(self):
        """Połączenia liczone w osobnym procesie (inny rdzeń procesora) i pokazane na płytach, zanim krok zostanie zapisany.
        Wpisywanie ustawień nie czeka: liczy się tylko ostatnia wartość, a siatki przychodzą gotowe z procesu."""
        if self.mode != 'ply_joints':
            return
        recipe = self._pj_recipe()
        if recipe is None:
            if self.override:
                self.override = {}
                self.refresh()
            return
        existing = hist.light(self.document.bodies)
        originals = {b.id: b for b in self.document.bodies}

        def compute():
            return hist.background(hist.ply_joints_preview_job, existing, recipe)

        def show(value, error):
            if self.mode != 'ply_joints':
                return
            if error:
                self.override = {}
                self.pj_status.setText(str(error))
            else:
                meshes, failed = value if isinstance(value, tuple) else (value or {}, [])
                out = {}
                for bid, (shape, mesh) in meshes.items():
                    body = originals.get(bid)
                    if body is not None:
                        out[bid] = replace(body, shape=shape, mesh=mesh)
                self.override = out
                self._pj_show_failed(failed)
            self.refresh()

        self.run_preview('ply_joints', compute, show)

    def _pj_show_failed(self, failed):
        """Połączenia, których nie da się wykonać: czerwona ramka w liście i opis - reszta wykonuje się normalnie."""
        self.pj_failed = dict(failed or [])
        for key, (row, combo) in self.pj_rows.items():
            bad = key in self.pj_failed
            row.setStyleSheet(('QFrame#plyrow{background:#fff3f1;border:1.5px solid #e0533b;border-radius:9px;}' if bad else
                               'QFrame#plyrow{background:#f6f9fc;border:1px solid #dbe6f0;border-radius:9px;}'
                               'QFrame#plyrow:hover{background:#eaf3fe;border-color:#9ccbf6;}'))
            row.setToolTip(f'Nie udało się połączyć: {self.pj_failed[key]}. Zmień rodzaj połączenia albo szerokość noska.' if bad else '')
        base = self.pj_status.text().split('\n')[0]
        if self.pj_failed:
            self.pj_status.setText(base + f'\nNie da się wykonać połączeń: {len(self.pj_failed)} (czerwona ramka) - pozostałe się wykonają.')
        else:
            self.pj_status.setText(base)

    # ------------------------------------------------------------------------------------------------- rozłóż / złóż
    FOLD_COMMANDS = {'ply_unfold': ('Rozłóż płyty', 'rozłożyć'), 'ply_fold': ('Złóż płyty', 'złożyć')}

    def _ply_fold_ids(self, seeds):
        """Płyty pudełka / mebla: wskazana płyta razem z płytami o tym samym zapamiętanym rozłożeniu, a bez niego -
        z płytami z jej grupy na liście obiektów (np. „Pudełko 1”). Zaznaczone płyty dochodzą do zestawu."""
        panels = [b for b in self.document.bodies if b.kind == 'solid' and pw.is_panel(b)]
        out = []
        for sid in seeds:
            body = self.document.get(sid)
            if body is None or not pw.is_panel(body):
                continue
            fold = body.meta['ply'].get('fold')
            if fold:
                group = [b.id for b in panels if (b.meta['ply'].get('fold') or {}).get('key') == fold.get('key') and b.folder == body.folder]
            elif body.folder:
                group = [b.id for b in panels if b.folder == body.folder]
            else:
                group = [body.id]
            out += [i for i in group if i not in out]
        return out

    def ply_fold_command(self, command):
        """Rozłóż / Złóż płyty: od razu na zaznaczonych płytach, a bez zaznaczenia - po wskazaniu płyty kliknięciem."""
        if self.busy:
            return
        if self.mode == 'plyfoldpick' and self._plyfold_cmd == command:
            self.set_mode(None)
            return
        ids = self._ply_fold_ids([i for i in self.selected if self.document.get(i) is not None])
        if ids:
            self.tools[command].setChecked(False)
            self.run_ply_fold(command, ids)
            return
        self.set_mode('plyfoldpick')
        self._plyfold_cmd = command
        self.tools[command].setChecked(True)
        self.view.setCursor(Qt.PointingHandCursor)
        title, what = self.FOLD_COMMANDS[command]
        self.hint(f'{title}: kliknij płytę pudełka / mebla, które chcesz {what}. Esc anuluje.')
        self.toast(f'Kliknij płytę, którą chcesz {what} razem z resztą pudełka.', 3000)

    def pick_ply_fold(self, x, y):
        bid = self.view.pick_body(x, y)
        body = self.document.get(bid) if bid else None
        if body is None or not pw.is_panel(body):
            self.toast('To nie jest płyta ze sklejki. Kliknij płytę zrobioną w zakładce Sklejka.')
            return
        command = getattr(self, '_plyfold_cmd', 'ply_unfold')
        self.set_mode(None)
        self.tools[command].setChecked(False)
        self.run_ply_fold(command, self._ply_fold_ids([body.id]))

    def run_ply_fold(self, command, ids):
        flat = command == 'ply_unfold'
        title = self.FOLD_COMMANDS[command][0]
        recipe = dict(type='ply_fold', ids=list(ids), flat=flat, key=uuid.uuid4().hex)
        bodies = self.document.bodies

        def build():
            return hist.run_ply_fold(bodies, recipe)

        def apply(result):
            self.document.commit(result, label=title, icon=command, op=recipe)
            self._tool_select(list(ids))

        def shown():
            self.view.fit_all()

        self.run_operation(title, build, apply, fit=True, after=shown)

    def apply_ply_joints(self):
        recipe = self._pj_recipe()
        if self.busy or recipe is None:
            self.toast('Brak stykających się płyt do połączenia.')
            return
        if not any(c['joint'] != 'none' for c in self.pj_contacts):
            self.toast('Wszystkie styki mają ustawione „Bez połączenia”.')
            return
        existing = list(self.document.bodies)

        def build():
            return hist.offloaded(hist.run_ply_joints, existing, recipe), recipe

        def apply(result):
            bodies, recipe_ = result
            self.document.pending_op = recipe_
            self.document.pending_label, self.document.pending_icon = 'Połączenia sklejki', 'ply_joints'
            self.document.commit(bodies)
            failed = [c['title'] for c in self.pj_contacts if c['key'] in getattr(self, 'pj_failed', {})]
            if failed:
                self.toast('Pominięte połączenia (nie dało się ich wykonać): ' + '; '.join(failed[:4]) + ('…' if len(failed) > 4 else ''), 8000)

        self.override = {}
        self.view.set_selection_meshes(None)
        self.run_operation('Połączenia sklejki', build, apply, after=lambda: self.set_mode(None))

    # ------------------------------------------------------------------ Do cięcia
    def _pc_bodies(self):
        """Płyty do zapisu: wszystkie widoczne albo (przełącznik „Zaznaczone”) tylko zaznaczone."""
        visible = [b for b in self.document.bodies if pw.is_panel(b) and b.visible]
        if self.pc_scope.currentData() == 'sel':
            return [b for b in visible if b.id in self.selected]
        return visible

    def _pc_params_changed(self):
        self.ply_cfg.update(sheet=float(self.pc_sheet.value()), kerf=float(self.pc_kerf.value()), labels=bool(self.pc_labels.isChecked()))
        self._ply_cfg_save()

    def _pc_update(self):
        if self.mode != 'ply_cut':
            return
        bodies = self._pc_bodies()
        self.pc_export.setText('Zapisz pliki STL…' if self.ply_method == 'print' else 'Zapisz DXF…')
        if not bodies:
            self.pc_list.setText('Nie zaznaczono żadnej płyty - zaznacz płyty albo wybierz „Wszystkie płyty”.' if self.pc_scope.currentData() == 'sel'
                                 else 'Brak płyt. Płyty powstają w narzędziach Płyta, Ścianka i Półka.')
            self.pc_status.setText('')
            return
        try:
            rows = pw.cut_list(bodies)
        except Exception as exc:
            self.pc_list.setText(str(exc))
            return
        lines = ['<table cellspacing="0" cellpadding="2">',
                 '<tr><td><b>Płyta</b></td><td align="right"><b>Wymiary</b></td><td align="right"><b>Gr.</b></td><td align="right"><b>Szt.</b></td></tr>']
        for r in rows:
            names = ', '.join(r['names'][:3]) + ('…' if len(r['names']) > 3 else '')
            lines.append(f"<tr><td>{names}</td><td align='right'>{r['size'][0]:g} × {r['size'][1]:g}</td>"
                         f"<td align='right'>{r['size'][2]:g}</td><td align='right'>{r['count']}</td></tr>")
        lines.append('</table>')
        self.pc_list.setText(''.join(lines))
        scope = 'zaznaczone płyty' if self.pc_scope.currentData() == 'sel' else 'wszystkie widoczne płyty'
        self.pc_status.setText(f'{len(bodies)} płyt ({scope}). ' + ('Każda płyta jako osobny plik STL, położona płasko.' if self.ply_method == 'print'
                                                                    else 'Jeden plik DXF 1:1 mm: warstwa CUT (cięcie na wylot), POCKET (gniazda, rowki), OPIS.'))

    def ply_export(self, path=None):
        bodies = self._pc_bodies()
        if not bodies:
            self.toast('Brak płyt do zapisania.')
            return
        meth = self.ply_method
        if path is None:
            if meth == 'print':
                path = QFileDialog.getExistingDirectory(self, 'Folder na pliki STL płyt')
            else:
                path, _ = QFileDialog.getSaveFileName(self, 'Zapisz płyty do cięcia', 'plyty.dxf', 'DXF (*.dxf)')
        if not path:
            return
        items = [(b.name, b.shape, (b.meta or {}).get('ply', {}).get('t')) for b in bodies]
        sheet, labels, kerf = float(self.pc_sheet.value()), bool(self.pc_labels.isChecked()), float(self.pc_kerf.value())

        def job():
            parts = [dict(name=n, flat=pw.flat_part(s, t)[0], t=pw.panel_info(s, t)['t']) for n, s, t in items]
            if meth == 'print':
                return len(pw.export_stl(parts, path))
            pw.export_dxf(parts, path, meth, labels, sheet, kerf if meth == 'laser' else 0.0)
            return len(parts)

        from .studio import _Work
        work = _Work(job)
        jobs = self.__dict__.setdefault('_export_jobs', [])
        jobs.append(work)
        self._exports = getattr(self, '_exports', 0) + 1
        name = Path(path).name

        def finished():
            self._exports -= 1
            if work in jobs:
                jobs.remove(work)

        def done(count):
            finished()
            self.toast(f'Zapisano {count} płyt: {name}.', 4500)
            self.pc_status.setText(f'Zapisano {count} płyt: {path}')

        def failed(message):
            finished()
            self.toast(f'Zapis płyt nie powiódł się: {message}', 6000)

        work.signals.done.connect(done)
        work.signals.failed.connect(failed)
        self.pool.start(work)
        self.toast(f'Zapisuję płyty: {name}…', 3000)
