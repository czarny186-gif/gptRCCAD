"""Okno „Wentylacja” (zakładka Obudowy) - etap 10 Generatora obudów.

Kroki: 1) ścianka obudowy (klik płaskiej ściany części obudowy), 2) obszar (środek, szerokość, wysokość albo
„Wypełnij ściankę”), 3) wzór i parametry. Podczas zmian - uproszczony podgląd (obrysy otworów, bez OCC), po chwili bez
zmian - dokładna geometria w tle (run_preview, wynik nieaktualny pomijany) z powierzchnią otwartą i jej udziałem.
Zastosuj: osobny krok historii „Wentylacja” (Cofnij / Ponów, zapis projektu). Geometria: rccad.enclosure_vents."""
from __future__ import annotations

import uuid

import numpy as np

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QPushButton, QSpinBox

from . import enclosure_holes as eh
from . import enclosure_vents as ev
from . import kernel
from . import shell_ui as ui
from .enclosure_ui import _label, _spin
from .enclosure_hole_ui import enclosure_bodies

VENT_LINE = (.1, .45, .85, 1)


def frame_of(recipe):
    n = np.asarray(recipe['normal'], float)
    up = (0, 0, 1.0) if abs(n[2]) < .9 else (0, 1.0, 0)
    return eh.wall_frame(recipe['point'], n, up)


class EnclosureVentTools:
    def _build_encvent_panel(self):
        self.ev = dict(target=None)
        self._ev_timer = QTimer(self)
        self._ev_timer.setSingleShot(True)
        self._ev_timer.setInterval(350)
        self._ev_timer.timeout.connect(lambda: self._ev_exact())
        self.ev_panel, lay = self._panel(300, 'Wentylacja', 'x_encvent', 'Ścianka → obszar → wzór', plain=True, scroll=True)
        self.ev_step1 = ui.StepRow(1, 'x_enclosure', 'Ścianka obudowy', plain=True)
        lay.addWidget(self.ev_step1)
        self.ev_step2 = ui.StepRow(2, 'x_encvent', 'Obszar', plain=True)
        lay.addWidget(self.ev_step2)
        fill = QPushButton('Wypełnij ściankę')
        fill.setToolTip('Obszar = cała ścianka nad wnętrzem obudowy (bez sąsiednich ścianek)')
        fill.clicked.connect(lambda _=False: self._ev_fill())
        lay.addWidget(fill)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        self.ev_f = {}
        d = ev.DEFAULTS
        rows = (('cu', 'Środek - w prawo', d['cu'], -1e4), ('cv', 'Środek - w górę', d['cv'], -1e4), ('width', 'Szerokość obszaru', d['width'], .1),
                ('height', 'Wysokość obszaru', d['height'], .1), ('size', 'Wielkość otworu', d['size'], .1), ('length', 'Długość szczeliny / otworu', d['length'], .1),
                ('pitch', 'Odstęp (0 = auto)', d['pitch'], 0.0), ('pitch2', 'Odstęp rzędów (0 = auto)', d['pitch2'], 0.0),
                ('angle', 'Kąt obrotu wzoru', d['angle'], -360), ('margin', 'Margines od krawędzi', d['margin'], 0.0),
                ('web', 'Min. materiał między otworami', d['web'], 0.0), ('louver', 'Kąt żaluzji', d['louver'], -75),
                ('fan_spacing', 'Rozstaw otworów wentylatora', ev.FANS[40][0], .1), ('fan_hole', 'Otwory montażowe wentylatora', ev.FANS[40][1], .1))
        for n, (key, title, val, low) in enumerate(rows):
            box = _spin(val, low, 1e4, 2, 1 if key in ('angle', 'louver', 'width', 'height') else .1, ' °' if key in ('angle', 'louver') else ' mm')
            box.valueChanged.connect(lambda *_: self._ev_update())
            label = _label(title, 'label')
            grid.addWidget(label, n, 0)
            grid.addWidget(box, n, 1)
            self.ev_f[key] = (label, box)
        for n, key in enumerate(('rows', 'cols')):
            box = QSpinBox()
            box.setRange(0, 500)
            box.setButtonSymbols(QSpinBox.NoButtons)
            box.setKeyboardTracking(False)
            box.valueChanged.connect(lambda *_: self._ev_update())
            label = _label('Rzędy (0 = auto)' if key == 'rows' else 'Kolumny (0 = auto)', 'label')
            grid.addWidget(label, len(rows) + n, 0)
            grid.addWidget(box, len(rows) + n, 1)
            self.ev_f[key] = (label, box)
        self.ev_step3 = ui.StepRow(3, 'x_encvent', 'Wzór otworów', plain=True)
        self.ev_pattern = QComboBox()
        for key in ev.PATTERNS:
            self.ev_pattern.addItem(ev.PATTERN_LABELS[key], key)
        self.ev_pattern.setCurrentIndex(self.ev_pattern.findData('hex'))
        self.ev_pattern.currentIndexChanged.connect(lambda *_: self._ev_update())
        self.ev_fan = QComboBox()
        for size in ev.FANS:
            self.ev_fan.addItem(f'Wentylator {size} mm', size)
        self.ev_fan.setCurrentIndex(self.ev_fan.findData(40))
        self.ev_fan.currentIndexChanged.connect(lambda *_: self._ev_fan_changed())
        lay.addLayout(grid)
        lay.addWidget(self.ev_step3)
        lay.addWidget(self.ev_pattern)
        lay.addWidget(self.ev_fan)
        self.ev_info = _label('', 'value')
        self.ev_info.setStyleSheet('font-weight:700; color:#17314a;')
        lay.addWidget(self.ev_info)
        self.ev_status = _label('Kliknij płaską ściankę obudowy.', 'status')
        lay.addWidget(self.ev_status)
        self.ev_apply, _ = self._buttons(self.ev_panel.footer, 'Zastosuj', 'Anuluj', self.apply_encvent, lambda: self.set_mode(None))
        # obszar i wzór: pola rozmieszczone w siatce wyżej, kolejność: obszar, potem wzór
        return self.ev_panel

    def _encvent_begin(self):
        self.ev = dict(target=None)
        self._ev_result = None
        self.ev_panel.show()
        if not enclosure_bodies(self.document.bodies):
            self.toast('W projekcie nie ma obudowy z Generatora obudów - najpierw Utwórz obudowę.')
        self.hint('Wentylacja: kliknij płaską ściankę obudowy, ustaw obszar i wzór otworów.')
        self.view.setCursor(Qt.PointingHandCursor)
        self._ev_update()

    def _ev_fan_changed(self):
        spacing, hole = ev.FANS[self.ev_fan.currentData()]
        for key, val in (('fan_spacing', spacing), ('fan_hole', hole)):
            box = self.ev_f[key][1]
            box.blockSignals(True)
            box.setValue(val)
            box.blockSignals(False)
        self._ev_update()

    def encvent_hover(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        mesh = None
        if body is not None and (body.meta or {}).get('enclosure'):
            try:
                face, _n = self.view.face_at(body, hit)
                mesh = kernel.display_mesh(face) if face is not None and kernel.is_planar_face(face) else None
            except Exception:
                mesh = None
        self.view.set_hover_mesh(mesh)

    def encvent_click(self, x, y, shift=False):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or not (body.meta or {}).get('enclosure'):
            self.toast('Kliknij ściankę obudowy z Generatora obudów.')
            return
        try:
            face, _n = self.view.face_at(body, hit)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        if face is None or not kernel.is_planar_face(face):
            self.toast('Wentylacja powstaje w płaskiej ściance.')
            return
        n = np.asarray(face.normalAt(face.Center()).toTuple(), float)
        self.ev['target'] = dict(id=body.id, point=[float(c) for c in face.Center().toTuple()], normal=[float(c) for c in n])
        self._ev_fill(update=False)
        self._ev_update()

    def _ev_fill(self, update=True):
        """Obszar = ścianka nad wnętrzem: ramka ściany w układzie ścianki pomniejszona o grubość ścianki (sąsiednie ścianki)."""
        t = self.ev.get('target')
        body = self.document.get(t['id']) if t else None
        if body is None:
            return
        frame = frame_of(t)
        face = next((f for f in body.shape.Faces() if f.geomType() == 'PLANE'
                     and float(np.asarray(f.normalAt(f.Center()).toTuple()) @ frame[3]) > 1 - 1e-6
                     and abs(float((np.asarray(f.Center().toTuple()) - frame[0]) @ frame[3])) < 1e-4), None)
        if face is None:
            return
        lo, hi, _uv = eh._bbox_uv(face.wrapped, frame)
        try:
            th = eh.wall_thickness(body.shape.wrapped, frame, ((lo + hi) / 2))
        except kernel.CadError:
            th = 2.0
        vals = dict(cu=(lo[0] + hi[0]) / 2, cv=(lo[1] + hi[1]) / 2, width=max(1.0, hi[0] - lo[0] - 2 * th - .2), height=max(1.0, hi[1] - lo[1] - 2 * th - .2))
        for key, val in vals.items():
            box = self.ev_f[key][1]
            box.blockSignals(True)
            box.setValue(round(float(val), 3))
            box.blockSignals(False)
        if update:
            self._ev_update()

    def ev_params(self):
        out = {k: (int(b.value()) if k in ('rows', 'cols') else float(b.value())) for k, (_l, b) in self.ev_f.items()}
        out.update(pattern=self.ev_pattern.currentData(), fan=self.ev_fan.currentData())
        return out

    def ev_recipe(self):
        t = self.ev.get('target')
        if t is None:
            return None
        return dict(type='enc_vent', target=t['id'], point=t['point'], normal=t['normal'], params=self.ev_params())

    def _ev_update(self):
        if not hasattr(self, 'ev_pattern') or self.mode != 'encvent':
            return
        pat = self.ev_pattern.currentData()
        show = {'length': pat in ('rect', 'slot', 'rslot', 'louver'), 'pitch2': pat not in ('radial', 'fan'), 'rows': pat not in ('radial', 'fan'),
                'cols': pat not in ('radial', 'fan'), 'louver': pat == 'louver', 'fan_spacing': pat == 'fan', 'fan_hole': pat == 'fan',
                'width': pat != 'fan', 'height': pat != 'fan'}
        for key, (label, box) in self.ev_f.items():
            vis = show.get(key, True)
            label.setVisible(vis)
            box.setVisible(vis)
        self.ev_fan.setVisible(pat == 'fan')
        t = self.ev.get('target')
        tb = self.document.get(t['id']) if t else None
        self.ev_step1.set_state('done' if tb else 'active', tb.name if tb else 'kliknij ściankę')
        self.ev_step2.set_state('done' if tb else 'pending', '')
        self.ev_step3.set_state('active', ev.PATTERN_LABELS[pat].lower())
        self.ev_apply.setEnabled(False)
        self._ev_timer.stop()
        recipe = self.ev_recipe()
        if recipe is None:
            self.view.set_preview_mesh(None)
            self.ev_info.setText('')
            return
        frame = frame_of(recipe)
        try:
            holes, area = ev.layout(dict(ev.DEFAULTS, **recipe['params']))
        except kernel.CadError as exc:
            self.view.set_preview_mesh(None)
            self.ev_status.setText(str(exc))
            self.ev_info.setText('')
            return
        self._ev_sig = repr(recipe)
        self.view.set_preview_mesh(ev.preview_mesh(holes, frame), color=(0, 0, 0, 0), line_color=VENT_LINE, width=1.6)   # uproszczony podgląd
        self.ev_info.setText(f'Otwory: {sum(1 for h in holes if h[4] == "vent")}')
        self.ev_status.setText('Uproszczony podgląd - dokładna geometria za chwilę…')
        self._ev_timer.start()

    def _ev_exact(self):
        recipe = self.ev_recipe()
        if recipe is None or self.mode != 'encvent':
            return
        sig = repr(recipe)
        bodies = list(self.document.bodies)

        def compute():
            shape, info = build(bodies, recipe)
            return dict(mesh=kernel.display_mesh(shape), info=info)

        def show(value, error):
            if self.mode != 'encvent' or getattr(self, '_ev_sig', None) != sig:
                return                                    # nieaktualny wynik
            if error or value is None:
                self.ev_status.setText(str(error) if error else 'Nie udało się policzyć wentylacji.')
                self.ev_apply.setEnabled(False)
                return
            info = value['info']
            self.view.set_preview_mesh(value['mesh'], color=(.55, .75, .95, .35), line_color=VENT_LINE, width=1.4)
            self.ev_info.setText(f'Otwory: {info["count"]}' + (f' (+{info["mounts"]} montażowe)' if info['mounts'] else '')
                                 + f'\nPowierzchnia otwarta: {info["open_area"]:.1f} mm² ({info["percent"]:.1f}% obszaru)')
            self.ev_status.setText('Enter albo Zastosuj wycina otwory (tylko w tej części obudowy).')
            self.ev_apply.setEnabled(True)
        self.run_preview('encvent', compute, show)

    def _step_fill_enc_vent(self, recipe):
        """Edycja kroku wentylacji: ścianka, obszar i wzór z przepisu."""
        p = dict(ev.DEFAULTS, **recipe['params'])
        self.ev['target'] = dict(id=recipe['target'], point=recipe['point'], normal=recipe['normal'])
        widgets = [self.ev_pattern, self.ev_fan, *[b for _l, b in self.ev_f.values()]]
        for w_ in widgets:
            w_.blockSignals(True)
        self.ev_pattern.setCurrentIndex(self.ev_pattern.findData(p['pattern']))
        self.ev_fan.setCurrentIndex(max(0, self.ev_fan.findData(int(p['fan']))))
        for k, (_l, box) in self.ev_f.items():
            if p.get(k) is not None:
                box.setValue(int(p[k]) if k in ('rows', 'cols') else float(p[k]))
        for w_ in widgets:
            w_.blockSignals(False)
        self._ev_update()

    def apply_encvent(self):
        if self.busy or self.mode != 'encvent' or not self.ev_apply.isEnabled():
            return
        recipe = self.ev_recipe()
        editing = (getattr(self, '_step_edit', None) or {}).get('recipe') or {}
        recipe['id'] = editing.get('id') if editing.get('type') == recipe['type'] and editing.get('id') else uuid.uuid4().hex
        recipe['seq'] = editing.get('seq') if editing.get('type') == recipe['type'] and 'seq' in editing else len(self.document.states())
        existing = list(self.document.bodies)

        def build_step():
            return run(existing, recipe)

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Wentylacja'
            self.document.pending_icon = 'encvent'
            self.document.commit(bodies)

        def after():
            self.view.set_preview_mesh(None)
            self._ev_update()

        self._ev_timer.stop()
        self.view.set_preview_mesh(None)
        self.run_operation('Wentylacja', build_step, apply, after=after)


def build(bodies, recipe):
    by_id = {b.id: b for b in bodies}
    target = by_id.get(recipe['target'])
    if target is None or target.kind != 'solid':
        raise kernel.CadError('Ścianki obudowy wskazanej dla wentylacji już nie ma.')
    return ev.build(target.shape, frame_of(recipe), recipe['params'])


def tools_only(recipe, target_shape):
    """Narzędzia otworów wentylacyjnych (do kontroli) - z części obudowy sprzed wycięcia."""
    return ev.tools(target_shape, frame_of(recipe), recipe['params'])


def run(bodies, recipe):
    """Krok historii 'enc_vent': otwory wentylacyjne w części obudowy (parametry Generatora zostają w meta)."""
    from dataclasses import replace
    shape, _info = build(bodies, recipe)
    out = []
    for b in bodies:
        if b.id == recipe['target']:
            meta = dict(b.meta or {})
            meta['enclosure_vents'] = [*[v for v in meta.get('enclosure_vents', []) if v.get('id') != recipe.get('id')],
                                       {k: recipe[k] for k in recipe if k != 'type'}]
            b = replace(b, shape=shape, meta=meta, mesh=None).prepared()
        out.append(b)
    return out
