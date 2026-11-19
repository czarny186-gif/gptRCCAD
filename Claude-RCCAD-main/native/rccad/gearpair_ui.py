"""Przekładnie → Para kół walcowych (zakładka Przekładnie).

Mixin okna Studio - tylko interfejs. Zazębienie liczy silnik rccad.gears.pair (bez Qt): liczba zębów koła 2 albo
przełożenie, odległość osi (0 = dobrana sama), korekcje (dobierane same albo korekcja koła 1 wpisana), kierunki
skrętu (para zewnętrzna - przeciwne, z wieńcem - ten sam), położenia kół w zazębieniu i kontrola: interferencja,
podcięcie, zaostrzenie, wskaźnik przyporu, luz wierzchołkowy.

Pola zależne aktualizują się same: w trybie „Liczba zębów” przełożenie pokazuje z2 / z1, w trybie „Przełożenie” liczba
zębów koła 2 wynika z przełożenia; kierunek skrętu koła 2 wynika z koła 1; korekcje i odległość osi - w ramce wyników.
Podgląd na żywo (szybka siatka obu kół), Podgląd - dokładne bryły B-Rep, Zastosuj - krok historii 'gear_pair' (dwie
bryły w jednej grupie). Dwuklik w koło pary albo Edytuj na kroku otwiera to okno z wartościami."""
from __future__ import annotations

import uuid

import numpy as np
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import history as hist
from . import kernel
from . import shell_ui as ui
from .gear_ui import FIELD_STYLE, LEVEL_COLORS, PREVIEW_COLOR, READOUT
from .gears import GearError
from .gears import pair as gp


class GearPairTools:
    def _build_gearpair_panel(self):
        from .studio import _label, _spin
        self.gearpair_panel, lay = self._panel(340, 'Para kół walcowych', 'x_gearpair', 'Przekładnie · dwa koła w zazębieniu', plain=True, scroll=True)
        d = gp.PairParams()
        self.gp_fields = {}

        def field(layout, name, title, spin, tip):
            spin.setToolTip(tip)
            label = _label(title)
            layout.addWidget(label)
            layout.addWidget(spin)
            spin.valueChanged.connect(lambda *_: self._gp_changed())
            self.gp_fields[name] = spin
            return spin

        def box():
            widget = QWidget()
            inner = QVBoxLayout(widget)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(11)
            return widget, inner

        self.gp_step1 = ui.StepRow(1, 'x_gearpair', 'Rodzaj pary', plain=True)
        lay.addWidget(self.gp_step1)
        self.gp_kind = ui.Segmented([('Para zewnętrzna', 'external', 'gp_ext'), ('Koło z wieńcem', 'internal', 'gp_int')], 34)
        self.gp_kind._buttons[0].setToolTip('Dwa koła zewnętrzne - obracają się w przeciwne strony.')
        self.gp_kind._buttons[1].setToolTip('Koło (zębnik) wewnątrz wieńca o zębach wewnętrznych - obracają się w tę samą stronę.')
        lay.addWidget(self.gp_kind)

        self.gp_step2 = ui.StepRow(2, 'gr_teeth', 'Liczba zębów i przełożenie', plain=True)
        lay.addWidget(self.gp_step2)
        field(lay, 'teeth1', 'Liczba zębów koła 1 (z₁)', _spin(d.teeth1, 1, 5000, 0, 1), 'Koło napędzające / zębnik.')
        self.gp_by = ui.Segmented([('Liczba zębów', 'teeth', 'gp_byteeth'), ('Przełożenie', 'ratio', 'gp_byratio')], 30)
        self.gp_by._buttons[0].setToolTip('Wpisujesz liczbę zębów koła 2 - przełożenie wylicza się samo.')
        self.gp_by._buttons[1].setToolTip('Wpisujesz przełożenie i = z₂ / z₁ - liczba zębów koła 2 dobiera się sama (najbliższa całkowita).')
        lay.addWidget(_label('Koło 2 określa'))
        lay.addWidget(self.gp_by)
        field(lay, 'teeth2', 'Liczba zębów koła 2 (z₂)', _spin(d.teeth2, 1, 5000, 0, 1), 'Koło napędzane / wieniec.')
        field(lay, 'ratio', 'Przełożenie i = z₂ / z₁', _spin(d.ratio, .01, 1000, 4, .1), 'Żądane przełożenie (w trybie Przełożenie).')

        self.gp_step3 = ui.StepRow(3, 'gr_teeth', 'Uzębienie', plain=True)
        lay.addWidget(self.gp_step3)
        field(lay, 'module', 'Moduł m (mm)', _spin(d.module, .01, 1000, 3, .25), 'Wspólny moduł obu kół (normalny).')
        field(lay, 'pressure', 'Kąt przyporu α (°)', _spin(d.pressure, 1, 60, 2, .5), 'Wspólny kąt przyporu (normalny), zwykle 20°.')
        field(lay, 'helix', 'Kąt pochylenia β (°)', _spin(d.helix, 0, 89, 2, 1), '0 - zęby proste. Zęby skośne: wspólny kąt pochylenia.')
        self.gp_hand_box, hb = box()
        self.gp_hand = ui.Segmented([('Prawy', 'right', 'gr_rh'), ('Lewy', 'left', 'gr_lh')], 30)
        hb.addWidget(_label('Kierunek skrętu koła 1'))
        hb.addWidget(self.gp_hand)
        self.gp_hand2 = _label('', 'small')
        hb.addWidget(self.gp_hand2)
        lay.addWidget(self.gp_hand_box)
        field(lay, 'width', 'Szerokość kół b (mm)', _spin(d.width, 0, 1e5, 3, 1), 'Szerokość wieńców obu kół.')
        field(lay, 'backlash', 'Luz międzyzębny j (mm)', _spin(d.backlash, 0, 100, 3, .02), 'Luz pary (normalny) - każde koło pocienione o połowę.')

        self.gp_step4 = ui.StepRow(4, 'gp_ext', 'Odległość osi i korekcja', plain=True)
        lay.addWidget(self.gp_step4)
        center = _spin(d.center, 0, 1e5, 4, .5)
        center.setSpecialValueText('dobrana sama')
        field(lay, 'center', 'Odległość osi a (mm)', center,
              'Odległość osi kół. „Dobrana sama” - bez zmiany albo z korekcją usuwającą podcięcie i interferencję; wpisana - '
              'korekcje dobierają się tak, by koła zazębiały się przy tej odległości.')
        self.gp_auto = QCheckBox('Dobierz korekcję zarysu automatycznie')
        self.gp_auto.setChecked(True)
        self.gp_auto.setToolTip('Najmniejsza korekcja bez podcięcia zębnika i bez interferencji. Wyłączone - wpisujesz korekcję koła 1, '
                                'korekcja koła 2 wynika z odległości osi.')
        self.gp_auto.toggled.connect(lambda *_: self._gp_changed())
        lay.addWidget(self.gp_auto)
        self.gp_shift_box, sb = box()
        field(sb, 'shift1', 'Korekcja koła 1 (x₁)', _spin(d.shift1, -3, 3, 3, .05), 'Współczynnik korekcji zarysu koła 1.')
        lay.addWidget(self.gp_shift_box)

        self.gp_step5 = ui.StepRow(5, 'gr_body', 'Otwory', plain=True)
        lay.addWidget(self.gp_step5)
        field(lay, 'bore1', 'Otwór koła 1 (mm)', _spin(d.bore1, 0, 1e5, 3, 1), 'Średnica otworu koła 1. 0 = bez otworu.')
        self.gp_ext_box, eb = box()
        field(eb, 'bore2', 'Otwór koła 2 (mm)', _spin(d.bore2, 0, 1e5, 3, 1), 'Średnica otworu koła 2. 0 = bez otworu.')
        lay.addWidget(self.gp_ext_box)
        self.gp_int_box, ib = box()
        rim = _spin(d.rim_diameter, 0, 1e5, 3, 1)
        rim.setSpecialValueText('dobrana sama')
        field(ib, 'rim_diameter', 'Średnica zewnętrzna wieńca (mm)', rim, 'Wieniec: średnica zewnętrzna. „Dobrana sama” - obręcz 1,2 wysokości zęba.')
        lay.addWidget(self.gp_int_box)

        self.gp_info = QLabel('—')
        self.gp_info.setObjectName('readout')
        self.gp_info.setWordWrap(True)
        self.gp_info.setTextFormat(Qt.RichText)
        self.gp_info.setStyleSheet(READOUT)
        lay.addWidget(self.gp_info)
        self.gp_note = _label('', 'small')
        self.gp_note.setWordWrap(True)
        lay.addWidget(self.gp_note)
        self.gp_status = _label('', 'status')
        self.gp_status.setWordWrap(True)
        self.gp_status.setTextFormat(Qt.RichText)
        lay.addWidget(self.gp_status)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.gp_preview_btn, self.gp_apply_btn, self.gp_cancel_btn = QPushButton('Podgląd'), QPushButton('Zastosuj'), QPushButton('Anuluj')
        self.gp_apply_btn.setObjectName('primary')
        self.gp_preview_btn.setToolTip('Dokładny podgląd: bryły B-Rep obu kół. Na żywo przy zmianie pól widać szybki podgląd.')
        self.gp_apply_btn.setToolTip('Tworzy oba koła w zazębieniu (Enter) - krok historii, edycja dwuklikiem w koło.')
        self.gp_cancel_btn.setToolTip('Zamyka narzędzie bez zmian - pola wracają do wartości sprzed otwarcia.')
        self.gp_preview_btn.clicked.connect(lambda _=False: self.preview_gearpair())
        self.gp_apply_btn.clicked.connect(lambda _=False: self.apply_gearpair())
        self.gp_cancel_btn.clicked.connect(lambda _=False: self.cancel_gearpair())
        for b in (self.gp_preview_btn, self.gp_apply_btn, self.gp_cancel_btn):
            row.addWidget(b)
        self.gearpair_panel.footer.addLayout(row)
        for seg in (self.gp_kind, self.gp_by, self.gp_hand):
            seg.currentIndexChanged.connect(lambda *_: self._gp_changed())
        self._gp_entry = None
        self.gp_result = None
        self.gp_checks = []
        self.gp_previewing = False
        self.gp_exact = False
        self._gp_timer = QTimer(self)
        self._gp_timer.setSingleShot(True)
        self._gp_timer.setInterval(60)
        self._gp_timer.timeout.connect(self._gp_preview)
        self._gp_syncing = False
        self._gp_changed()

    # ---------- parametry <-> pola ----------
    def gearpair_params(self):
        v = {name: float(spin.value()) for name, spin in self.gp_fields.items()}
        return gp.PairParams(kind=self.gp_kind.currentData(), teeth1=int(round(v['teeth1'])), teeth2=int(round(v['teeth2'])),
                             by_ratio=self.gp_by.currentData() == 'ratio', ratio=v['ratio'], module=v['module'],
                             pressure=v['pressure'], helix=v['helix'], hand=self.gp_hand.currentData(), width=v['width'],
                             backlash=v['backlash'], center=v['center'], auto_shift=self.gp_auto.isChecked(),
                             shift1=v['shift1'], bore1=v['bore1'], bore2=v['bore2'], rim_diameter=v['rim_diameter'])

    def set_gearpair_params(self, params):
        p = params if isinstance(params, gp.PairParams) else gp.PairParams.from_dict(params)
        widgets = [self.gp_kind, self.gp_by, self.gp_hand, self.gp_auto, *self.gp_fields.values()]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.gp_kind.setCurrentIndex(self.gp_kind.findData(p.kind))
            self.gp_by.setCurrentIndex(1 if p.by_ratio else 0)
            self.gp_hand.setCurrentIndex(self.gp_hand.findData(p.hand))
            self.gp_auto.setChecked(p.auto_shift)
            data = p.to_dict()
            for name, spin in self.gp_fields.items():
                spin.setValue(float(data[name]))
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._gp_changed()

    def _gp_sync(self, p):
        """Pola zależne: przełożenie z liczby zębów albo liczba zębów koła 2 z przełożenia."""
        self._gp_syncing = True
        try:
            if p.by_ratio:
                spin = self.gp_fields['teeth2']
                spin.blockSignals(True)
                spin.setValue(p.z2)
                spin.blockSignals(False)
            else:
                spin = self.gp_fields['ratio']
                spin.blockSignals(True)
                spin.setValue(p.teeth2 / max(p.teeth1, 1))
                spin.blockSignals(False)
        finally:
            self._gp_syncing = False
        self.gp_fields['teeth2'].setEnabled(not p.by_ratio)
        self.gp_fields['ratio'].setEnabled(p.by_ratio)

    # ---------- obliczenia i kontrola na bieżąco ----------
    def _gp_changed(self):
        if getattr(self, '_gp_syncing', False):
            return
        p = self.gearpair_params()
        self._gp_sync(p)
        self.gp_hand_box.setVisible(p.helical)
        self.gp_ext_box.setVisible(not p.internal)
        self.gp_int_box.setVisible(p.internal)
        self.gp_shift_box.setVisible(not p.auto_shift)
        if p.helical:
            other = p.hand if p.internal else ('left' if p.hand == 'right' else 'right')
            self.gp_hand2.setText(f'Koło 2: {"prawy" if other == "right" else "lewy"} '
                                  f'({"ten sam - wieniec" if p.internal else "przeciwny - para zewnętrzna"})')
        try:
            result = gp.solve(p)
            checks = list(result.checks)
        except GearError as exc:
            result, checks = None, [gp.Check('error', '', str(exc))]
        self.gp_result, self.gp_checks = result, checks
        worst = {}
        for c in checks:
            if c.field and worst.get(c.field) != 'error':
                worst[c.field] = c.level
        for name, spin in self.gp_fields.items():
            level = worst.get(name)
            spin.setStyleSheet(FIELD_STYLE.format(LEVEL_COLORS[level]) if level else '')
        errors = [c for c in checks if c.level == 'error']
        warnings = [c for c in checks if c.level == 'warning']
        lines = [f'<span style="color:#c4373c;font-weight:700;">✖ {c.message}</span>' for c in errors]
        lines += [f'<span style="color:#9a6512;">⚠ {c.message}</span>' for c in warnings]
        self.gp_status.setText('<br>'.join(lines) or '<span style="color:#22794f;font-weight:700;">✔ Koła zazębiają się poprawnie.</span>')
        self._gp_info(p, result)
        self.gp_step1.set_state('done', gp.PAIR_TITLES[p.kind])
        self.gp_step2.set_state('active' if any(c.field in ('teeth1', 'teeth2', 'ratio') for c in errors) else 'done',
                                f'z₁ {p.teeth1} · z₂ {p.z2} · i = {p.z2 / max(p.teeth1, 1):.3f}')
        self.gp_step3.set_state('done', f'm {p.module:g} · α {p.pressure:g}°' + (f' · β {p.helix:g}°' if p.helical else ' · zęby proste'))
        self.gp_step4.set_state('active' if any(c.field in ('center', 'shift1') for c in errors) else 'done',
                                f'a = {result.center:.3f} mm' if result else '')
        self.gp_step5.set_state('done', '')
        self.gp_preview_btn.setEnabled(not errors)
        self.gp_apply_btn.setEnabled(not errors)
        if self.gp_previewing and self.mode == 'gearpair':
            self.gp_exact = False
            if errors:
                self.view.set_preview_mesh(None)
                self.gp_note.setText('')
            else:
                self._gp_timer.start()

    def _gp_info(self, p, r):
        if r is None:
            self.gp_info.setText('Wyniki pojawią się po poprawieniu pól.')
            return
        g1, g2 = r.gear1, r.gear2
        from .gears import derived
        d1, d2 = derived(g1), derived(g2)
        hand = lambda g: ('prawy' if g.hand == 'right' else 'lewy') if p.helical else 'proste'
        rows = [f'Przełożenie i: <b>{r.ratio:.4f}</b>' + (f' (żądane {p.ratio:g})' if p.by_ratio else ''),
                f'Odległość osi a: <b>{r.center:.4f} mm</b>' + (f' (bez korekcji {r.center0:.4f})' if abs(r.center - r.center0) > 1e-6 else ''),
                f'Toczny kąt przyporu α<sub>w</sub>: <b>{r.alpha_w:.3f}°</b>',
                f'Wskaźnik przyporu ε<sub>α</sub>: <b>{r.contact_ratio:.3f}</b>' + (f' · ε<sub>β</sub>: <b>{r.overlap_ratio:.3f}</b>' if p.helical else ''),
                f'Luz wierzchołkowy: <b>{min(r.clearance1, r.clearance2):.3f} mm</b>']
        for n, g, d in ((1, g1, d1), (2, g2, d2)):
            rows.append(f'Koło {n}: z <b>{g.teeth}</b> · x <b>{g.shift:+.3f}</b> · d <b>{d["d"]:.3f}</b> · d<sub>a</sub> <b>{d["da"]:.3f}</b> '
                        f'· d<sub>f</sub> <b>{d["df"]:.3f}</b> · {hand(g)}')
        self.gp_info.setText('<br>'.join(rows))

    # ---------- wejście, podgląd, przyciski ----------
    def _gearpair_enter(self):
        self.gearpair_panel.show()
        self._gp_entry = self.gearpair_params()
        self.gp_previewing = True
        self.gp_exact = False
        self._gp_changed()
        self._gp_timer.stop()
        self._gp_preview()
        self.view.setCursor(Qt.ArrowCursor)
        self.hint('Para kół: liczba zębów albo przełożenie, moduł, odległość osi - koła ustawiają się w zazębieniu, podgląd odświeża się od razu.')

    def _gp_valid(self):
        self._gp_changed()
        errors = [c for c in self.gp_checks if c.level == 'error']
        if errors:
            self.toast(errors[0].message)
            return False
        return True

    def _gp_show(self, mesh, exact):
        self.view.set_preview_mesh(mesh, **PREVIEW_COLOR)
        self.gp_exact = exact
        self.gp_note.setText('Podgląd: dokładne bryły B-Rep.' if exact else
                             'Podgląd szybki (siatka) - dokładne bryły B-Rep powstają po Zastosuj; przycisk Podgląd pokazuje je od razu.')

    def _gp_preview(self):
        if self.mode != 'gearpair' or not self.gp_previewing or self.gp_result is None:
            return
        if [c for c in self.gp_checks if c.level == 'error']:
            return
        params, result = self.gearpair_params(), self.gp_result

        def compute():
            from .gears import preview
            from .meshbool import triangles_shape
            verts, tris, offset = [], [], 0
            for g, place in ((result.gear1, result.place1), (result.gear2, result.place2)):
                v, t = preview.mesh_arrays(g)
                M = np.asarray(place, float)
                verts.append(v @ M[:, :3].T + M[:, 3])
                tris.append(t + offset)
                offset += len(v)
            return kernel.triangle_mesh_display(triangles_shape(np.vstack(verts), np.vstack(tris)))

        def show(mesh, error):
            if self.mode != 'gearpair' or not self.gp_previewing or self.gearpair_params() != params or self.gp_exact:
                return
            if error or mesh is None:
                self.view.set_preview_mesh(None)
                return
            self._gp_show(mesh, False)

        self.run_preview('gearpair', compute, show)

    def preview_gearpair(self):
        """Dokładny podgląd: bryły B-Rep obu kół w zazębieniu (w tle)."""
        if not self._gp_valid():
            return
        self.gp_previewing = True
        self._gp_timer.stop()
        params, result = self.gearpair_params(), self.gp_result

        def compute():
            import cadquery as cq
            shapes = [hist.apply_placement(hist.gear_shape(g), np.asarray(place, float))
                      for g, place in ((result.gear1, result.place1), (result.gear2, result.place2))]
            return kernel.display_mesh(cq.Compound.makeCompound(shapes), .1)

        def show(mesh, error):
            if self.mode != 'gearpair' or self.gearpair_params() != params:
                return
            if error or mesh is None:
                self.toast(error or 'Nie udało się zbudować kół.')
                return
            self._gp_show(mesh, True)

        self.run_preview('gearpair', compute, show)

    def _gp_editing(self):
        recipe = (getattr(self, '_step_edit', None) or {}).get('recipe') or {}
        return recipe if recipe.get('type') == 'gear_pair' else None

    def apply_gearpair(self):
        if self.busy or not self._gp_valid():
            return
        params = self.gearpair_params()
        editing = self._gp_editing()
        ids = list((editing or {}).get('out') or ())
        ids += [uuid.uuid4().hex for _ in range(2 - len(ids))]
        recipe = dict(type='gear_pair', params=params.to_dict(), out=ids[:2])
        existing = list(self.document.bodies)

        def build():
            return list(hist.run_gear_pair(existing, recipe))

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Para kół zębatych'
            self.document.pending_icon = 'gearpair'
            self.document.commit(bodies)
            self.selected = list(ids[:2])

        self._gp_entry = params
        self.gp_previewing = False
        self._gp_timer.stop()
        self.view.set_preview_mesh(None)
        self.run_operation('Para kół zębatych', build, apply, after=lambda: self.set_mode(None))

    def cancel_gearpair(self):
        if self._gp_entry is not None:
            self.set_gearpair_params(self._gp_entry)
        self.gp_previewing = False
        self._gp_timer.stop()
        self.set_mode(None)

    def _step_fill_gear_pair(self, recipe):
        """Edycja kroku historii (dwuklik w koło pary / Edytuj): okno z parametrami pary; Zastosuj zastępuje krok."""
        self.set_gearpair_params(recipe['params'])
        self._gp_entry = self.gearpair_params()
