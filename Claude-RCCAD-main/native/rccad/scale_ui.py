"""Skalowanie (przycisk w prawym górnym rogu, obok płaszczyzn): zmiana rozmiaru brył i szkiców - całych grup naraz.

Mixin okna Studio: panel, wybór obiektów (zaznaczone albo kliknięte), natychmiastowy podgląd macierzą (bez liczenia
geometrii) i krok historii 'scale' (history.run_scale)."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import history as hist
from . import kernel
from . import shell_ui as ui

SCALE_ANCHORS = (('Środek', 'center', 'sc_center'), ('Spód', 'bottom', 'sc_bottom'), ('Początek', 'origin', 'sc_origin'))


class ScaleTools:
    def _build_scale_panel(self):
        from .studio import _label, _spin
        self.scale_panel, lay = self._panel(312, 'Skalowanie', 'x_scale', 'Zmiana rozmiaru obiektów i szkiców', plain=True, scroll=True)
        self.sc_step1 = ui.StepRow(1, 'x_object', 'Obiekty', plain=True)
        lay.addWidget(self.sc_step1)
        self.sc_value = _spin(100.0, .01, 1e6, 3, 10)
        self.sc_value.setToolTip('Skala w procentach: 200 - dwa razy większy, 50 - o połowę mniejszy.')
        self._pic_field(lay, 'Skala (%)', 'x_scale', self.sc_value, 'Ten sam współczynnik w każdym kierunku.')
        self.sc_axes = QCheckBox('Różna skala w osiach X, Y, Z')
        lay.addWidget(self.sc_axes)
        self.sc_axes_box = QWidget()
        col = QVBoxLayout(self.sc_axes_box)          # osie jedna pod drugą - pola mieszczą się w panelu
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        self.sc_xyz = []
        for axis, color in zip('XYZ', ('#e5484d', '#2fa56d', '#3b82f6')):
            spin = _spin(100.0, .01, 1e6, 3, 10)
            spin.setToolTip(f'Skala w osi {axis} (%) - albo przeciągnij strzałkę osi {axis}')
            row = QHBoxLayout()
            row.setSpacing(10)
            name = QLabel(f'{axis} (%)')
            name.setStyleSheet(f'color:{color};font-weight:700;')
            name.setFixedWidth(46)
            row.addWidget(name)
            row.addWidget(spin, 1)
            col.addLayout(row)
            self.sc_xyz.append(spin)
        lay.addWidget(self.sc_axes_box)
        self.sc_axes_box.hide()
        self.sc_anchor = ui.Segmented(list(SCALE_ANCHORS), 30)
        for button, tip in zip(self.sc_anchor._buttons, ('Środek obiektów zostaje w miejscu.',
                                                          'Spód obiektów zostaje na swojej wysokości (stoją dalej na podłożu), środek w poziomie w miejscu.',
                                                          'Początek układu współrzędnych (0, 0, 0) zostaje w miejscu.')):
            button.setToolTip(tip)
        self._field(lay, 'Punkt, który zostaje w miejscu', self.sc_anchor)
        self.sc_size = _label('', 'help')
        self.sc_size.setWordWrap(True)
        lay.addWidget(self.sc_size)
        self.sc_status = _label('Zaznacz obiekty albo kliknij obiekt na polu roboczym.', 'status')
        self.sc_status.setWordWrap(True)
        lay.addWidget(self.sc_status)
        self._buttons(self.scale_panel.footer, 'Zastosuj', 'Zamknij', self.apply_scale, lambda: self.set_mode(None))
        self.sc_ids = []
        self.sc_value.valueChanged.connect(lambda *_: self._sc_update())
        for spin in self.sc_xyz:
            spin.valueChanged.connect(lambda *_: self._sc_update())
        self.sc_axes.toggled.connect(self._sc_axes_toggled)
        self.sc_anchor.currentIndexChanged.connect(lambda *_: self._sc_update())

    # ------------------------------------------------------------------ tryb
    def toggle_scale(self, on=None):
        on = (self.mode != 'scale') if on is None else on
        self.set_mode('scale' if on else None)

    def _scale_enter(self):
        self.scale_panel.show()
        self.scale_button.setChecked(True)
        self.view.setCursor(Qt.PointingHandCursor)
        self.sc_value.blockSignals(True)
        self.sc_value.setValue(100.0)
        self.sc_value.blockSignals(False)
        for spin in self.sc_xyz:
            spin.blockSignals(True)
            spin.setValue(100.0)
            spin.blockSignals(False)
        targets = []
        for i in self.selected:
            for j in self._group_ids(i):
                if j not in targets and self.document.get(j) is not None:
                    targets.append(j)
        self._sc_set(targets)
        self.hint('Skalowanie: wpisz skalę w procentach; Enter zatwierdza.')

    def _sc_axes_toggled(self, on):
        self.sc_axes_box.setVisible(on)
        if on:
            for spin in self.sc_xyz:
                spin.blockSignals(True)
                spin.setValue(self.sc_value.value())
                spin.blockSignals(False)
        self.sc_value.setEnabled(not on)
        self._sc_update()

    def pick_scale(self, x, y, shift=False):
        bid = self.pick_object(x, y)
        body = self.document.get(bid) if bid else None
        if body is None:
            self.toast('Kliknij bryłę albo szkic.')
            return
        ids = self._group_ids(body.id)
        if shift:
            if all(i in self.sc_ids for i in ids):
                targets = [i for i in self.sc_ids if i not in ids]
            else:
                targets = [*self.sc_ids, *[i for i in ids if i not in self.sc_ids]]
        else:
            targets = ids
        self._sc_set(targets)

    def _sc_set(self, ids):
        self.view.clear_body_matrices()
        self.sc_ids = list(ids)
        self.selected = list(ids)
        self.refresh()
        self._sc_update()

    # ------------------------------------------------------------------ wartości
    def _sc_factors(self):
        if self.sc_axes.isChecked():
            return [max(1e-6, s.value() / 100.0) for s in self.sc_xyz]
        f = max(1e-6, self.sc_value.value() / 100.0)
        return [f, f, f]

    def _sc_box(self):
        bodies = [self.document.get(i) for i in self.sc_ids]
        bodies = [b for b in bodies if b is not None]
        if not bodies:
            return None
        return kernel.bounds(kernel.compound([b.shape for b in bodies]) if len(bodies) > 1 else bodies[0].shape)

    def _sc_center(self, box=None):
        box = box or self._sc_box()
        anchor = self.sc_anchor.currentData()
        if anchor == 'origin' or box is None:
            return [0.0, 0.0, 0.0]
        c = box.center.toTuple()
        if anchor == 'bottom':
            return [float(c[0]), float(c[1]), float(box.zmin)]
        return [float(v) for v in c]

    def _sc_update(self):
        if self.mode != 'scale':
            return
        box = self._sc_box()
        n = len(self.sc_ids)
        if box is None:
            self.view.set_handles([])
            self.sc_step1.set_state('active', 'Kliknij obiekt (Shift - kolejne)')
            self.sc_size.setText('')
            self.sc_status.setText('Zaznacz obiekty albo kliknij obiekt na polu roboczym (Shift + klik dodaje kolejne).')
            self.view.clear_body_matrices()
            return
        names = self.document.get(self.sc_ids[0]).name
        self.sc_step1.set_state('done', names if n == 1 else f'{names} + {n - 1}')
        f = self._sc_factors()
        size = (box.xlen, box.ylen, box.zlen)
        fmt = lambda v: f'{v:.2f}'.rstrip('0').rstrip('.').replace('.', ',')
        self.sc_size.setText('Wymiary: ' + ' × '.join(fmt(v) for v in size) + ' mm  →  ' + ' × '.join(fmt(v * k) for v, k in zip(size, f)) + ' mm')
        self.sc_status.setText('Enter albo Zastosuj zmienia rozmiar' + (' całej grupy.' if n > 1 else '.'))
        m = kernel.scale_matrix(f, self._sc_center(box))
        q = QMatrix4x4(*[float(v) for v in m.flatten()])
        self.view.set_body_matrices({i:q for i in self.sc_ids})
        self._sc_handles(box, f)

    def _sc_handles(self, box, f):
        """Strzałki skalowania: jedna (po przekątnej, skala jednakowa) albo trzy - osobno dla osi X, Y, Z."""
        if self._hv is not None:
            return                                  # w trakcie przeciągania strzałka zostaje pod kursorem
        c = np.array(self._sc_center(box), float)
        anchor=self.document.get(self.sc_ids[-1]) if self.sc_ids else None
        visual=kernel.bounds(anchor.shape) if anchor is not None else box
        lo = np.array([visual.xmin, visual.ymin, visual.zmin], float)
        hi = np.array([visual.xmax, visual.ymax, visual.zmax], float)
        f = np.array(f, float)
        lo2, hi2 = c + (lo - c) * f, c + (hi - c) * f
        size = float(max(np.max(hi2 - lo2), 1.0))
        length = max(12.0, size * .3)
        handles = []
        if self.sc_axes.isChecked():
            mid = (lo2 + hi2) / 2
            for k, (axis, color) in enumerate(zip('XYZ', ((.9, .28, .3, 1), (.18, .65, .43, 1), (.23, .51, .96, 1)))):
                d = np.eye(3)[k]
                start = mid.copy()
                start[k] = hi2[k]
                handles.append(dict(id='sc' + axis, start=start, tip=start + d * length, dir=d, color=color, label=axis))
        else:
            d = np.ones(3) / np.sqrt(3)
            handles.append(dict(id='scA', start=hi2, tip=hi2 + d * length, dir=d, color=(.94, .6, .13, 1), label=''))
        self.view.set_handles(handles)

    def scale_handle_dragged(self, hid, delta):
        """Przeciąganie strzałki skali: przesunięcie końca strzałki o delta mm zmienia skalę tak, żeby róg (koniec) obiektu
        szedł za kursorem."""
        box = self._sc_box()
        if box is None:
            return
        c = np.array(self._sc_center(box), float)
        hi = np.array([box.xmax, box.ymax, box.zmax], float)
        if hid == 'scA':
            if self._hv is None:
                self._hv = self.sc_value.value()
            reach = float(np.linalg.norm(hi - c)) or 1.0
            self.sc_value.setValue(max(.01, round(self._hv + delta / reach * 100.0, 1)))
            return
        k = 'XYZ'.index(hid[2])
        spin = self.sc_xyz[k]
        if self._hv is None:
            self._hv = spin.value()
        reach = float(hi[k] - c[k]) or 1.0
        spin.setValue(max(.01, round(self._hv + delta / reach * 100.0, 1)))

    def apply_scale(self):
        if self.busy:
            return
        ids = [i for i in self.sc_ids if self.document.get(i) is not None]
        if not ids:
            self.toast('Zaznacz albo kliknij obiekt do skalowania.')
            return
        f = self._sc_factors()
        if all(abs(v - 1) < 1e-12 for v in f):
            self.toast('Skala 100% - rozmiar się nie zmienia.')
            return
        recipe = dict(type='scale', ids=ids, f=[float(v) for v in f], center=self._sc_center())
        existing = list(self.document.bodies)

        def build():
            return hist.run_scale(existing, recipe)

        def apply(bodies):
            self.view.clear_body_matrices()
            self.document.pending_op = recipe
            self.document.pending_label, self.document.pending_icon = 'Skalowanie', 'scale'
            self.document.commit(bodies)
            self.selected = list(ids)

        self.run_operation('Skalowanie', build, apply, after=lambda: self.set_mode(None))
