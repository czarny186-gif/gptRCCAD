"""Pochylenie ścianki (zakładka Edycja).

Mixin okna Studio. Po włączeniu okno prosi o kliknięcie płaskiej ściany bryły. Na ścianie pojawiają się cztery strzałki
(przy jej czterech bokach): pociągnięcie strzałki podnosi albo opuszcza ten bok, a przeciwległy bok zostaje na miejscu -
ściana się pochyla, a reszta bryły rozciąga się do nowej płaszczyzny (history.tilt_face). Podgląd liczy się w tle.
Zastosuj zapisuje krok historii 'tilt', Zamknij zamyka narzędzie bez zmian."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QPushButton

from . import history as hist
from . import kernel
from . import shell_ui as ui

SIDES = (('U-', 'lewy'), ('U+', 'prawy'), ('V-', 'dolny'), ('V+', 'górny'))
COLORS = ((.94, .6, .13, 1), (.94, .6, .13, 1), (.11, .51, .81, 1), (.11, .51, .81, 1))


class TiltTools:
    def _build_tilt_panel(self):
        from .studio import _label, _spin
        self.tilt_panel, lay = self._panel(300, 'Pochylenie ścianki', 'x_tilt', 'Pochyl ścianę, bryła się dopasuje', plain=True, scroll=True)
        lay.addWidget(ui.StepRow(1, 'x_object', 'Kliknij płaską ściankę', plain=True))
        self.tl_status = _label('Kliknij płaską ścianę bryły, którą chcesz pochylić.', 'status')
        self.tl_status.setWordWrap(True)
        lay.addWidget(self.tl_status)
        lay.addWidget(ui.StepRow(2, 'x_tilt', 'Pociągnij strzałkę', plain=True))
        self.tl_spins = []
        for key, name in SIDES:
            lay.addWidget(_label(f'Bok {name}: podniesienie (mm)'))
            spin = _spin(0.0, -1e4, 1e4, 2, .5)
            spin.setToolTip('Ile ten bok ściany wysuwa się na zewnątrz (+) albo chowa w bryłę (-). Przeciwległy bok zostaje na miejscu.')
            spin.valueChanged.connect(lambda *_: self._tl_changed())
            lay.addWidget(spin)
            self.tl_spins.append(spin)
        self.tl_angles = _label('', 'help')
        self.tl_angles.setWordWrap(True)
        lay.addWidget(self.tl_angles)
        reset = QPushButton('Wyzeruj')
        reset.clicked.connect(lambda _=False: self._tl_set([0, 0, 0, 0]))
        lay.addWidget(reset)
        self.tl_apply, close = self._buttons(self.tilt_panel.footer, 'Zastosuj', 'Zamknij', self.apply_tilt, lambda: self.set_mode(None))
        self.tl_apply.setToolTip('Zapisuje pochylenie ściany (krok historii, można cofnąć).')
        close.setToolTip('Zamyka narzędzie bez zmian.')
        self.tl_face = None
        self._tl_timer = QTimer(self)
        self._tl_timer.setSingleShot(True)
        self._tl_timer.setInterval(60)
        self._tl_timer.timeout.connect(self._tl_preview)

    # ---------- wejście / wybór ściany ----------
    def _tilt_enter(self):
        self.tilt_panel.show()
        self.tl_face = None
        self._tl_set([0, 0, 0, 0], preview=False)
        self.view.setCursor(Qt.PointingHandCursor)
        self.tl_status.setText('Kliknij płaską ścianę bryły, którą chcesz pochylić.')
        self.tl_apply.setEnabled(False)
        self.hint('Pochylenie ścianki: kliknij płaską ścianę bryły, potem pociągnij jedną ze strzałek.')

    def pick_tilt(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij płaską ścianę bryły.')
            return
        try:
            face, normal = self.view.face_at(body, hit)
            if not kernel.is_planar_face(face):
                raise kernel.CadError('Pochylić można tylko płaską ścianę.')
            frame = hist.tilt_frame(body.shape, face)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        point = tuple(float(c) for c in hit[2])
        self.tl_face = dict(id=body.id, face=face, frame=frame, ref=hist.face_ref(face, frame[3], point, body.shape),
                            mesh=kernel.display_mesh(face))
        self._tl_set([0, 0, 0, 0], preview=False)
        self.tl_status.setText(f'Ściana bryły {body.name}. Pociągnij strzałkę przy boku, który ma się podnieść albo opuścić.')
        self.view.set_selection_meshes([self.tl_face['mesh']], color=(1, .55, .1, .35), line_color=(.95, .42, .02, 1))
        self._tl_handles()

    # ---------- wartości, strzałki, podgląd ----------
    def _tl_heights(self):
        return [float(s.value()) for s in self.tl_spins]

    def _tl_set(self, values, preview=True):
        for spin, value in zip(self.tl_spins, values):
            spin.blockSignals(True)
            spin.setValue(float(value))
            spin.blockSignals(False)
        if preview:
            self._tl_changed()
        else:
            self._tl_angles_text()

    def _tl_changed(self):
        self._tl_angles_text()
        if self.tl_face is None:
            return
        self._tl_handles()
        self.tl_apply.setEnabled(any(abs(h) > 1e-9 for h in self._tl_heights()))
        self._tl_timer.start()

    def _tl_angles_text(self):
        if self.tl_face is None:
            self.tl_angles.setText('')
            return
        _, _, _, _, u0, u1, v0, v1 = self.tl_face['frame']
        a, b, c, d = self._tl_heights()
        au = math.degrees(math.atan2(b - a, max(u1 - u0, 1e-9)))
        av = math.degrees(math.atan2(d - c, max(v1 - v0, 1e-9)))
        self.tl_angles.setText(f'Pochylenie: {au:+.1f}° wzdłuż szerokości, {av:+.1f}° wzdłuż wysokości ściany.')

    def _tl_side_points(self):
        """Środki czterech boków ściany na jej nowej (pochylonej) płaszczyźnie."""
        o, x, y, n, u0, u1, v0, v1 = self.tl_face['frame']
        a, b, c, d = self._tl_heights()
        w, h = max(u1 - u0, 1e-9), max(v1 - v0, 1e-9)
        um, vm = (u0 + u1) / 2, (v0 + v1) / 2

        def at(u, v):
            z = a * (u1 - u) / w + b * (u - u0) / w + c * (v1 - v) / h + d * (v - v0) / h
            return o + x * u + y * v + n * z

        return [at(u0, vm), at(u1, vm), at(um, v0), at(um, v1)], n

    def _tl_handles(self):
        if self.mode != 'tilt' or self.tl_face is None:
            self.view.set_handles([])
            return
        points, n = self._tl_side_points()
        frame = self.tl_face['frame']
        size = max(frame[5] - frame[4], frame[7] - frame[6])
        length = max(size * .25, float(self.view.opts['distance']) * .07)
        handles = []
        for i, (point, (key, name)) in enumerate(zip(points, SIDES)):
            handles.append(dict(id=f'tl{i}', start=point, tip=point + n * length, dir=n, color=COLORS[i], label='', min_px=36))
        self.view.set_handles(handles)

    def tilt_handle_dragged(self, hid, delta):
        i = int(hid[2:])
        if self._hv is None or self._hv[0] != hid:
            self._hv = (hid, self.tl_spins[i].value())
        self.tl_spins[i].setValue(round(self._hv[1] + float(delta), 2))

    def _tl_preview(self):
        if self.mode != 'tilt' or self.tl_face is None:
            return
        heights = self._tl_heights()
        body = self.document.get(self.tl_face['id'])
        if body is None:
            return
        if not any(abs(h) > 1e-9 for h in heights):
            self.view.set_preview_mesh(None)
            return
        shape, face = body.shape, self.tl_face['face']

        def compute():
            return kernel.display_mesh(hist.tilt_face(shape, face, heights), .2)

        def show(mesh, error):
            if self.mode != 'tilt' or self.tl_face is None or self._tl_heights() != heights:
                return
            if error or mesh is None:
                self.view.set_preview_mesh(None)
                self.tl_status.setText(error or 'Tego pochylenia nie da się wykonać.')
                return
            self.tl_status.setText('Podgląd: tak będzie wyglądała bryła. Zastosuj zapisuje zmianę, Zamknij - bez zmian.')
            self.view.set_preview_mesh(mesh, color=(.3, .75, .5, .55), line_color=(.05, .4, .2, 1), width=2)

        self.run_preview('tilt', compute, show)

    def apply_tilt(self):
        if self.busy or self.tl_face is None:
            self.toast('Kliknij płaską ścianę bryły.')
            return
        heights = self._tl_heights()
        if not any(abs(h) > 1e-9 for h in heights):
            self.toast('Pociągnij strzałkę albo wpisz podniesienie boku.')
            return
        body_id = self.tl_face['id']
        recipe = dict(type='tilt', id=body_id, face=self.tl_face['ref'], heights=heights)
        existing = list(self.document.bodies)

        def build():
            return list(hist.run_tilt(existing, recipe))

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Pochylenie ścianki'
            self.document.pending_icon = 'tilt'
            self.document.commit(bodies)

        self.view.set_handles([])
        self.view.set_preview_mesh(None)
        self.run_operation('Pochylenie ścianki', build, apply, after=lambda: self.set_mode(None))
