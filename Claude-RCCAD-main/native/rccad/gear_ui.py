"""Przekładnie → Koła walcowe (zakładka Przekładnie).

Mixin okna Studio - tylko interfejs. Obliczenia i sprawdzanie parametrów są w niezależnym silniku rccad.gears
(bez Qt), który później posłuży też przekładniom planetarnym i zębatkowym.

Etap 2: wymiary i zarys zęba liczy silnik (gears.check: walidacja + zarys ewolwentowy z obtaczania), panel pokazuje
podziałkę, grubość zęba i podcięcie stopy.
Etap 1: panel z rodzajem uzębienia (proste / skośne, zewnętrzne / wewnętrzne), polami parametrów i walidacją na bieżąco
(błędne pole obramowane na czerwono, ostrzeżenie na pomarańczowo, wymiary koła w ramce). Podgląd, Zastosuj i Anuluj
sprawdzają parametry - bryła koła powstaje dopiero w kolejnym etapie."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QVBoxLayout

from . import gears
from . import shell_ui as ui

KIND_ICONS = {'spur_ext': 'gr_spur_ext', 'helical_ext': 'gr_helical_ext', 'spur_int': 'gr_spur_int', 'helical_int': 'gr_helical_int'}
FIELD_STYLE = ('QDoubleSpinBox{{background:#fff;border:1.8px solid {0};border-radius:6px;padding:5px 7px;color:#254c71;'
               'font-size:12px;min-height:18px;}}')
LEVEL_COLORS = {'error': '#e5484d', 'warning': '#e2a23a'}
READOUT = ('QLabel#readout{background:#f3f6fa;border:1.4px solid #d6e0ea;border-radius:8px;padding:7px 10px;'
           'font-weight:600;color:#27415a;}')
GENERATION_LATER = 'Bryła koła powstanie w kolejnym etapie budowy modułu - teraz program tylko sprawdza parametry.'


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
        self.gr_preview_btn.setToolTip('Sprawdza parametry i pokazuje koło w widoku (bryła - w kolejnym etapie).')
        self.gr_apply_btn.setToolTip('Tworzy koło zębate (Enter). Na tym etapie tylko sprawdza parametry.')
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
        self._gr_changed()

    # ---------- parametry <-> pola ----------
    def gear_params(self):
        """Parametry z pól panelu (GearParams silnika)."""
        values = {name: float(spin.value()) for name, spin in self.gr_fields.items()}
        values['teeth'] = int(round(values['teeth']))
        return gears.GearParams(kind=self.gr_kind.currentData(), hand=self.gr_hand.currentData(), hub=self.gr_hub.isChecked(), **values)

    def set_gear_params(self, params):
        """Wpisuje parametry (GearParams albo słownik) do pól panelu."""
        p = params if isinstance(params, gears.GearParams) else gears.GearParams.from_dict(params)
        widgets = [self.gr_kind, self.gr_hand, self.gr_hub, *self.gr_fields.values()]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.gr_kind.setCurrentIndex(self.gr_kind.findData(p.kind))
            self.gr_hand.setCurrentIndex(self.gr_hand.findData(p.hand))
            self.gr_hub.setChecked(bool(p.hub))
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
        self.gr_step2.set_state('active' if any(c.field not in ('bore', 'hub_diameter', 'hub_length', 'rim_diameter') for c in errors) else 'done',
                                f'm {p.module:g} · z {p.teeth}' + (f' · β {p.beta:g}° {"prawy" if p.hand == "right" else "lewy"}' if p.helical else ''))
        body_error = any(c.field in ('bore', 'hub_diameter', 'hub_length', 'rim_diameter') for c in errors)
        self.gr_step3.set_state('active' if body_error else 'done', self._gr_body_text(p))
        self.gr_preview_btn.setEnabled(not errors)
        self.gr_apply_btn.setEnabled(not errors)

    def _gr_body_text(self, p):
        if p.internal:
            return 'wieniec ' + (f'Ø{p.rim_diameter:g}' if p.rim_diameter > 0 else 'dobrany sam')
        text = f'otwór Ø{p.bore:g}' if p.bore > 0 else 'bez otworu'
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
            rows.append(('Średnica wieńca', g['rim']))
        text = '<br>'.join(f'{name}: <b>{value:.3f} mm</b>' for name, value in rows)
        prof = getattr(self, 'gr_profile', None)
        if prof is not None and not p.internal:
            text += ('<br>Podcięcie stopy: <b style="color:#9a6512;">tak</b> (bez podcięcia: korekcja x ≥ '
                     f'{g["x_min"]:.3f})' if prof.undercut else '<br>Podcięcie stopy: <b>brak</b>')
        self.gr_info.setText(text)

    # ---------- wejście / przyciski ----------
    def _gear_enter(self):
        self.gear_panel.show()
        self._gr_entry = self.gear_params()          # Anuluj przywraca pola sprzed otwarcia
        self._gr_changed()
        self.view.setCursor(Qt.ArrowCursor)
        self.hint('Koła walcowe: wybierz rodzaj uzębienia i wpisz parametry. Błędne pole podświetla się na czerwono.')

    def _gr_valid(self):
        self._gr_changed()
        errors = [c for c in self.gr_checks if c.level == 'error']
        if errors:
            self.toast(errors[0].message)
            return False
        return True

    def preview_gear(self):
        if self._gr_valid():
            self.toast('Parametry koła poprawne. ' + GENERATION_LATER)

    def apply_gear(self):
        if not self._gr_valid():
            return
        self._gr_entry = self.gear_params()           # zaakceptowane wartości zostają w polach
        self.toast('Parametry koła poprawne. ' + GENERATION_LATER)

    def cancel_gear(self):
        if self._gr_entry is not None:
            self.set_gear_params(self._gr_entry)
        self.set_mode(None)
