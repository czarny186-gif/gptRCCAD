"""Przekładnie → Koła walcowe (zakładka Przekładnie).

Mixin okna Studio - tylko interfejs. Obliczenia i sprawdzanie parametrów są w niezależnym silniku rccad.gears
(bez Qt), który później posłuży też przekładniom planetarnym i zębatkowym.

Etap 3: Podgląd liczy w tle bryłę koła o zębach prostych (zielony podgląd odświeża się przy zmianie pól), Zastosuj
dodaje ją jako krok historii 'gear' (przepis = parametry; dwuklik w krok otwiera to okno z wartościami). Rowek wpustowy
wg DIN 6885 (pola 0 = wartości z normy).
Etap 4: także zęby skośne (zewnętrzne i wewnętrzne) - ramka pokazuje skok linii zęba i skręt na szerokości; koło
wewnętrzne - grubość obręczy (kontrola wg ISO 6336-3).
Etap 2: wymiary i zarys zęba liczy silnik (gears.check: walidacja + zarys ewolwentowy z obtaczania), panel pokazuje
podziałkę, grubość zęba i podcięcie stopy.
Etap 1: panel z rodzajem uzębienia (proste / skośne, zewnętrzne / wewnętrzne), polami parametrów i walidacją na bieżąco
(błędne pole obramowane na czerwono, ostrzeżenie na pomarańczowo, wymiary koła w ramce). Podgląd, Zastosuj i Anuluj
sprawdzają parametry - bryła koła powstaje dopiero w kolejnym etapie."""
from __future__ import annotations

import math
import uuid

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QVBoxLayout

from . import gears
from . import history as hist
from . import kernel
from . import shell_ui as ui

KIND_ICONS = {'spur_ext': 'gr_spur_ext', 'helical_ext': 'gr_helical_ext', 'spur_int': 'gr_spur_int', 'helical_int': 'gr_helical_int'}
FIELD_STYLE = ('QDoubleSpinBox{{background:#fff;border:1.8px solid {0};border-radius:6px;padding:5px 7px;color:#254c71;'
               'font-size:12px;min-height:18px;}}')
LEVEL_COLORS = {'error': '#e5484d', 'warning': '#e2a23a'}
READOUT = ('QLabel#readout{background:#f3f6fa;border:1.4px solid #d6e0ea;border-radius:8px;padding:7px 10px;'
           'font-weight:600;color:#27415a;}')
PREVIEW_COLOR = dict(color=(.3, .75, .5, .55), line_color=(.05, .4, .2, 1), width=2)


class GridSegmented(ui.Segmented):
    """Segmented z przyciskami w siatce (np. 2 x 2) - cztery rodzaje uzębienia mieszczą się w wąskim panelu."""

    def __init__(self, items, icon_size=34, columns=2, parent=None):
        super().__init__(items, icon_size, parent)
        old = self.layout()
        for button in self._buttons:
            old.removeWidget(button)
        QWidget().setLayout(old)            # zabiera stary układ (poziomy), żeby ustawić siatkę
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        for i, button in enumerate(self._buttons):
            grid.addWidget(button, i // columns, i % columns)


class GearTools:
    def _build_gear_panel(self):
        from .studio import _label, _spin
        self.gear_panel, lay = self._panel(330, 'Koła walcowe', 'x_gear', 'Przekładnie · parametryczne koło zębate', plain=True, scroll=True)
        self.gr_step1 = ui.StepRow(1, 'x_gear', 'Rodzaj uzębienia', plain=True)
        lay.addWidget(self.gr_step1)
        self.gr_kind = GridSegmented([(gears.KIND_TITLES[k], k, KIND_ICONS[k]) for k in gears.KINDS], 34, 2)
        tips = {'spur_ext': 'Zęby proste na zewnątrz koła (zwykłe koło walcowe).',
                'helical_ext': 'Zęby skośne na zewnątrz koła - cichsza praca, siła osiowa.',
                'spur_int': 'Zęby proste do środka pierścienia (wieniec, np. przekładnia planetarna).',
                'helical_int': 'Zęby skośne do środka pierścienia.'}
        for button, key in zip(self.gr_kind._buttons, self.gr_kind._data):
            button.setToolTip(tips[key])
        lay.addWidget(self.gr_kind)

        self.gr_step2 = ui.StepRow(2, 'gr_teeth', 'Uzębienie', plain=True)
        lay.addWidget(self.gr_step2)
        d = gears.GearParams()
        self.gr_fields = {}

        def field(layout, name, title, spin, tip):
            spin.setToolTip(tip)
            label = _label(title)
            layout.addWidget(label)
            layout.addWidget(spin)
            spin.valueChanged.connect(lambda *_: self._gr_changed())
            self.gr_fields[name] = spin
            spin.title_label = label
            return spin

        field(lay, 'module', 'Moduł m (mm)', _spin(d.module, .01, 1000, 3, .25),
              'Moduł normalny: podziałka zębów / π. Koła współpracujące muszą mieć ten sam moduł i kąt przyporu.')
        field(lay, 'teeth', 'Liczba zębów z', _spin(d.teeth, 1, 5000, 0, 1),
              'Liczba zębów koła (liczba całkowita).')
        field(lay, 'pressure', 'Kąt przyporu α (°)', _spin(d.pressure, 1, 60, 2, .5),
              'Kąt przyporu zarysu odniesienia (normalny). Najczęściej 20°.')
        self.gr_helix_box = QWidget()
        box = QVBoxLayout(self.gr_helix_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(11)
        field(box, 'helix', 'Kąt pochylenia β (°)', _spin(d.helix, 0, 89, 2, 1),
              'Kąt pochylenia linii zęba względem osi koła (zęby skośne). Koła współpracujące: ten sam kąt, przeciwne kierunki '
              '(koło wewnętrzne: ten sam kierunek).')
        self.gr_hand = ui.Segmented([('Prawy', 'right', 'gr_rh'), ('Lewy', 'left', 'gr_lh')], 30)
        self.gr_hand._buttons[0].setToolTip('Prawoskrętne: linia zęba wznosi się w prawo (patrząc z boku koła).')
        self.gr_hand._buttons[1].setToolTip('Lewoskrętne: linia zęba wznosi się w lewo.')
        box.addWidget(_label('Kierunek skrętu'))
        box.addWidget(self.gr_hand)
        lay.addWidget(self.gr_helix_box)
        field(lay, 'width', 'Szerokość koła b (mm)', _spin(d.width, 0, 1e5, 3, 1), 'Szerokość wieńca zębatego (wzdłuż osi koła).')
        field(lay, 'shift', 'Korekcja zarysu x', _spin(d.shift, -5, 5, 3, .05),
              'Współczynnik przesunięcia zarysu (×m). Dodatnia odsuwa zarys od środka koła: przy kole zewnętrznym ząb grubszy '
              'i bez podcięcia przy małej liczbie zębów. 0 = bez korekcji.')
        field(lay, 'backlash', 'Luz międzyzębny j (mm)', _spin(d.backlash, 0, 100, 3, .02),
              'Luz pary kół (normalny, po obwodzie). Każde koło pary jest pocienione o połowę luzu.')

        self.gr_step3 = ui.StepRow(3, 'gr_body', 'Korpus koła', plain=True)
        lay.addWidget(self.gr_step3)
        self.gr_ext_box = QWidget()
        box = QVBoxLayout(self.gr_ext_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(11)
        field(box, 'bore', 'Średnica otworu (mm)', _spin(d.bore, 0, 1e5, 3, 1), 'Otwór na wałek w osi koła. 0 = bez otworu.')
        self.gr_hub = QCheckBox('Piasta')
        self.gr_hub.setToolTip('Walcowa piasta wystająca z jednej strony koła (na wałek).')
        self.gr_hub.toggled.connect(lambda *_: self._gr_changed())
        box.addWidget(self.gr_hub)
        self.gr_hub_box = QWidget()
        hub = QVBoxLayout(self.gr_hub_box)
        hub.setContentsMargins(0, 0, 0, 0)
        hub.setSpacing(11)
        field(hub, 'hub_diameter', 'Średnica piasty (mm)', _spin(20.0, 0, 1e5, 3, 1), 'Średnica zewnętrzna piasty - większa niż otwór.')
        field(hub, 'hub_length', 'Długość piasty (mm)', _spin(8.0, 0, 1e5, 3, 1), 'O ile piasta wystaje poza wieniec zębaty.')
        box.addWidget(self.gr_hub_box)
        self.gr_keyway = QCheckBox('Rowek wpustowy (DIN 6885)')
        self.gr_keyway.setToolTip('Rowek na wpust pryzmatyczny w otworze, przez koło i piastę, pod osią pierwszego zęba.')
        self.gr_keyway.toggled.connect(lambda *_: self._gr_changed())
        box.addWidget(self.gr_keyway)
        self.gr_key_box = QWidget()
        key = QVBoxLayout(self.gr_key_box)
        key.setContentsMargins(0, 0, 0, 0)
        key.setSpacing(11)
        for name, title, tip in (('key_width', 'Szerokość rowka b (mm)', 'Szerokość rowka wpustowego. 0 = wg DIN 6885-1 dla średnicy otworu.'),
                                 ('key_depth', 'Głębokość rowka t₂ (mm)', 'Głębokość rowka w piaście, od powierzchni otworu. 0 = wg DIN 6885-1.')):
            spin = _spin(0.0, 0, 1e4, 2, .5)
            spin.setSpecialValueText('wg normy')
            field(key, name, title, spin, tip)
        box.addWidget(self.gr_key_box)
        lay.addWidget(self.gr_ext_box)
        self.gr_int_box = QWidget()
        box = QVBoxLayout(self.gr_int_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(11)
        field(box, 'rim_diameter', 'Średnica zewnętrzna wieńca (mm)', _spin(d.rim_diameter, 0, 1e5, 3, 1),
              'Koło wewnętrzne to pierścień: jego średnica zewnętrzna. 0 = dobrana sama (2,5·m materiału pod stopami zębów).')
        lay.addWidget(self.gr_int_box)

        self.gr_info = QLabel('—')
        self.gr_info.setObjectName('readout')
        self.gr_info.setWordWrap(True)
        self.gr_info.setTextFormat(Qt.RichText)
        self.gr_info.setStyleSheet(READOUT)
        lay.addWidget(self.gr_info)
        self.gr_status = _label('', 'status')
        self.gr_status.setWordWrap(True)
        self.gr_status.setTextFormat(Qt.RichText)
        lay.addWidget(self.gr_status)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.gr_preview_btn, self.gr_apply_btn, self.gr_cancel_btn = QPushButton('Podgląd'), QPushButton('Zastosuj'), QPushButton('Anuluj')
        self.gr_apply_btn.setObjectName('primary')
        self.gr_preview_btn.setToolTip('Pokazuje bryłę koła w widoku (zielony podgląd) - potem odświeża się sam przy zmianie pól.')
        self.gr_apply_btn.setToolTip('Tworzy koło zębate jako nową bryłę (Enter) - krok historii, można cofnąć i edytować dwuklikiem.')
        self.gr_cancel_btn.setToolTip('Zamyka narzędzie bez zmian - pola wracają do wartości sprzed otwarcia.')
        self.gr_preview_btn.clicked.connect(lambda _=False: self.preview_gear())
        self.gr_apply_btn.clicked.connect(lambda _=False: self.apply_gear())
        self.gr_cancel_btn.clicked.connect(lambda _=False: self.cancel_gear())
        for b in (self.gr_preview_btn, self.gr_apply_btn, self.gr_cancel_btn):
            row.addWidget(b)
        self.gear_panel.footer.addLayout(row)
        self.gr_kind.currentIndexChanged.connect(lambda *_: self._gr_changed())
        self.gr_hand.currentIndexChanged.connect(lambda *_: self._gr_changed())
        self._gr_entry = None
        self.gr_checks = []
        self.gr_previewing = False                    # po Podglądzie podgląd odświeża się przy każdej zmianie pól
        self._gr_timer = QTimer(self)
        self._gr_timer.setSingleShot(True)
        self._gr_timer.setInterval(250)
        self._gr_timer.timeout.connect(self._gr_preview)
        self._gr_changed()

    # ---------- parametry <-> pola ----------
    def gear_params(self):
        """Parametry z pól panelu (GearParams silnika)."""
        values = {name: float(spin.value()) for name, spin in self.gr_fields.items()}
        values['teeth'] = int(round(values['teeth']))
        return gears.GearParams(kind=self.gr_kind.currentData(), hand=self.gr_hand.currentData(), hub=self.gr_hub.isChecked(),
                                keyway=self.gr_keyway.isChecked(), **values)

    def set_gear_params(self, params):
        """Wpisuje parametry (GearParams albo słownik) do pól panelu."""
        p = params if isinstance(params, gears.GearParams) else gears.GearParams.from_dict(params)
        widgets = [self.gr_kind, self.gr_hand, self.gr_hub, self.gr_keyway, *self.gr_fields.values()]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.gr_kind.setCurrentIndex(self.gr_kind.findData(p.kind))
            self.gr_hand.setCurrentIndex(self.gr_hand.findData(p.hand))
            self.gr_hub.setChecked(bool(p.hub))
            self.gr_keyway.setChecked(bool(p.keyway))
            data = p.to_dict()
            for name, spin in self.gr_fields.items():
                spin.setValue(float(data[name]))
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._gr_changed()

    # ---------- walidacja na bieżąco ----------
    def _gr_changed(self):
        p = self.gear_params()
        self.gr_helix_box.setVisible(p.helical)
        self.gr_ext_box.setVisible(not p.internal)
        self.gr_int_box.setVisible(p.internal)
        self.gr_hub_box.setVisible(not p.internal and p.hub)
        self.gr_key_box.setVisible(not p.internal and p.keyway)
        self.gr_checks, self.gr_profile = gears.check(p)       # walidacja liczbowa i próba zbudowania zarysu zęba
        worst = {}
        for c in self.gr_checks:
            if c.field and worst.get(c.field) != 'error':
                worst[c.field] = c.level
        for name, spin in self.gr_fields.items():
            level = worst.get(name)
            spin.setStyleSheet(FIELD_STYLE.format(LEVEL_COLORS[level]) if level else '')
        errors = [c for c in self.gr_checks if c.level == 'error']
        warnings = [c for c in self.gr_checks if c.level == 'warning']
        self._gr_info(p, errors)
        lines = [f'<span style="color:#c4373c;font-weight:700;">✖ {c.message}</span>' for c in errors]
        lines += [f'<span style="color:#9a6512;">⚠ {c.message}</span>' for c in warnings]
        if not lines:
            lines = ['<span style="color:#22794f;font-weight:700;">✔ Parametry poprawne.</span>']
        self.gr_status.setText('<br>'.join(lines))
        self.gr_step1.set_state('done', gears.KIND_TITLES[p.kind])
        self.gr_step2.set_state('active' if any(c.field not in ('bore', 'hub_diameter', 'hub_length', 'rim_diameter', 'key_width', 'key_depth') for c in errors) else 'done',
                                f'm {p.module:g} · z {p.teeth}' + (f' · β {p.beta:g}° {"prawy" if p.hand == "right" else "lewy"}' if p.helical else ''))
        body_error = any(c.field in ('bore', 'hub_diameter', 'hub_length', 'rim_diameter', 'key_width', 'key_depth') for c in errors)
        self.gr_step3.set_state('active' if body_error else 'done', self._gr_body_text(p))
        self.gr_preview_btn.setEnabled(not errors)
        self.gr_apply_btn.setEnabled(not errors)
        if getattr(self, 'gr_previewing', False) and self.mode == 'gear':
            if errors:
                self.view.set_preview_mesh(None)
            else:
                self._gr_timer.start()

    def _gr_body_text(self, p):
        if p.internal:
            return 'wieniec ' + (f'Ø{p.rim_diameter:g}' if p.rim_diameter > 0 else 'dobrany sam')
        text = f'otwór Ø{p.bore:g}' if p.bore > 0 else 'bez otworu'
        key = gears.keyway_size(p)
        text += f' · rowek {key[0]:g}×{key[1]:g}' if key else ''
        return text + (f' · piasta Ø{p.hub_diameter:g}×{p.hub_length:g}' if p.hub else '')

    def _gr_info(self, p, errors):
        if any(c.field in ('module', 'teeth', 'pressure', 'helix', 'shift', 'backlash', 'kind') for c in errors):
            self.gr_info.setText('Wymiary koła pojawią się po poprawieniu pól.')
            return
        g = gears.derived(p)
        rows = [('Średnica podziałowa d', g['d']), ('Średnica głów d<sub>a</sub>', g['da']), ('Średnica stóp d<sub>f</sub>', g['df']),
                ('Średnica zasadnicza d<sub>b</sub>', g['db']), ('Wysokość zęba h', g['height'])]
        if p.helical:
            rows.insert(1, ('Moduł czołowy m<sub>t</sub>', g['mt']))
        rows += [('Podziałka czołowa p<sub>t</sub>' if p.helical else 'Podziałka p', g['pt']),
                 ('Grubość zęba s (na d)', g['s'])]
        if p.internal:
            rows += [('Średnica wieńca', g['rim']), ('Grubość obręczy s<sub>R</sub>', g['rim_thickness'])]
        if p.helical:
            from .gears import occ
            rows.append(('Skok linii zęba L', occ.lead(p)))
        text = '<br>'.join(f'{name}: <b>{value:.3f} mm</b>' for name, value in rows)
        if p.helical:
            from .gears import occ
            text += f'<br>Skręt zęba na szerokości: <b>{abs(math.degrees(occ.twist_angle(p))):.2f}°</b> ({"prawy" if p.hand == "right" else "lewy"})'
        prof = getattr(self, 'gr_profile', None)
        if prof is not None and not p.internal:
            text += ('<br>Podcięcie stopy: <b style="color:#9a6512;">tak</b> (bez podcięcia: korekcja x ≥ '
                     f'{g["x_min"]:.3f})' if prof.undercut else '<br>Podcięcie stopy: <b>brak</b>')
        self.gr_info.setText(text)

    # ---------- wejście / przyciski ----------
    def _gear_enter(self):
        self.gear_panel.show()
        self._gr_entry = self.gear_params()          # Anuluj przywraca pola sprzed otwarcia
        self.gr_previewing = False
        self._gr_changed()
        self.view.setCursor(Qt.ArrowCursor)
        self.hint('Koła walcowe: wybierz rodzaj uzębienia i wpisz parametry. Podgląd pokazuje koło, Zastosuj dodaje je do modelu.')

    def _gr_valid(self):
        self._gr_changed()
        errors = [c for c in self.gr_checks if c.level == 'error']
        if errors:
            self.toast(errors[0].message)
            return False
        return True

    def preview_gear(self):
        """Podgląd bryły koła (w tle); dalej odświeża się sam przy zmianie pól, aż do Zastosuj / Anuluj."""
        if not self._gr_valid():
            return
        self.gr_previewing = True
        self._gr_timer.stop()
        self._gr_preview()

    def _gr_preview(self):
        if self.mode != 'gear' or not self.gr_previewing:
            return
        params = self.gear_params()
        if [c for c in self.gr_checks if c.level == 'error']:
            return

        def compute():
            from .gears import occ
            return kernel.display_mesh(occ.gear_solid(params), .1)

        def show(mesh, error):
            if self.mode != 'gear' or not self.gr_previewing or self.gear_params() != params:
                return
            if error or mesh is None:
                self.view.set_preview_mesh(None)
                self.toast(error or 'Nie udało się zbudować koła.')
                return
            self.view.set_preview_mesh(mesh, **PREVIEW_COLOR)

        self.run_preview('gear', compute, show)

    def _gr_editing(self):
        """Przepis edytowanego kroku 'gear' (dwuklik w krok historii) albo None."""
        recipe = (getattr(self, '_step_edit', None) or {}).get('recipe') or {}
        return recipe if recipe.get('type') == 'gear' else None

    def apply_gear(self):
        if self.busy or not self._gr_valid():
            return
        params = self.gear_params()
        editing = self._gr_editing()
        ids = list((editing or {}).get('out') or ()) or [uuid.uuid4().hex]
        recipe = dict(type='gear', params=params.to_dict(), name=hist.gear_name(params), out=ids[:1])
        existing = list(self.document.bodies)

        def build():
            return list(hist.run_gear(existing, recipe))

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Koło zębate'
            self.document.pending_icon = 'gear'
            self.document.commit(bodies)
            self.selected = [ids[0]]

        self._gr_entry = params                       # zaakceptowane wartości zostają w polach
        self.gr_previewing = False
        self._gr_timer.stop()
        self.view.set_preview_mesh(None)
        self.run_operation('Koło zębate', build, apply, after=lambda: self.set_mode(None))

    def cancel_gear(self):
        if self._gr_entry is not None:
            self.set_gear_params(self._gr_entry)
        self.gr_previewing = False
        self._gr_timer.stop()
        self.set_mode(None)

    def _step_fill_gear(self, recipe):
        """Edycja kroku historii (dwuklik): okno z parametrami koła; Zastosuj zastępuje krok (ta sama bryła)."""
        self.set_gear_params(recipe['params'])
        self._gr_entry = self.gear_params()
        self.preview_gear()
