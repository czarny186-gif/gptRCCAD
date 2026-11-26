"""Generator obudów - etap 15 (okna): biblioteka szablonów w oknie „Utwórz obudowę” (wczytanie, zapis własnego,
sposób montażu) oraz zestawienie i eksport w „Kontroli obudowy”. Logika: rccad.enclosure_library."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QPushButton

from . import enclosure as enc
from . import enclosure_library as lib
from . import kernel
from .enclosure_ui import _label

MOUNTINGS = (('', 'Bez dodatkowego montażu'), ('din', 'Rowek pod szynę DIN TS35'), ('wall', 'Uszy do montażu na ścianie'))
FORMATS = (('step', 'STEP'), ('stl', 'STL'), ('3mf', '3MF'), ('dxf', 'DXF'), ('svg', 'SVG'), ('report', 'Zestawienie'))


class EnclosureLibraryTools:
    # ------------------------------------------------------------------ szablony (okno „Utwórz obudowę”)
    def _build_enc_templates(self, lay):
        lay.addWidget(_label('Szablon obudowy:', 'label'))
        self.enc_tpl = QComboBox()
        self.enc_tpl.setToolTip('Gotowe konfiguracje i szablony użytkownika - parametry i reguły, bez geometrii')
        lay.addWidget(self.enc_tpl)
        row = QHBoxLayout()
        row.setSpacing(6)
        load = QPushButton('Wczytaj szablon')
        load.clicked.connect(lambda _=False: self.enc_template_load(self.enc_tpl.currentData()))
        save = QPushButton('Zapisz jako szablon…')
        save.setToolTip('Zapisuje bieżące parametry i reguły (bez elementów) w „Ustawienia/Szablony obudów”')
        save.clicked.connect(lambda _=False: self.enc_template_save())
        row.addWidget(load)
        row.addWidget(save)
        lay.addLayout(row)
        self.enc_tpl_info = _label('', 'status')
        self.enc_tpl_info.setWordWrap(True)
        lay.addWidget(self.enc_tpl_info)
        self.enc_mounting = QComboBox()
        for key, title in MOUNTINGS:
            self.enc_mounting.addItem(title, key)
        self.enc_mounting.setToolTip('Sposób montażu obudowy (dno podstawy)')
        self.enc_mounting.currentIndexChanged.connect(lambda *_: self._enc_params_changed())
        lay.addWidget(self.enc_mounting)
        self.enc['rules'] = []
        self._enc_tpl_fill()

    def _enc_tpl_fill(self, select=None):
        self.enc_tpl.blockSignals(True)
        self.enc_tpl.clear()
        try:
            templates = lib.all_templates()
        except OSError:
            templates = dict(lib.TEMPLATES)
        self._enc_templates = templates
        for key, (name, desc, _p, _r) in templates.items():
            self.enc_tpl.addItem(name, key)
            self.enc_tpl.setItemData(self.enc_tpl.count() - 1, desc, 3)       # Qt.ToolTipRole
        if select:
            self.enc_tpl.setCurrentIndex(max(0, self.enc_tpl.findData(select)))
        self.enc_tpl.blockSignals(False)

    def enc_template_load(self, key):
        """Parametry szablonu do okna (elementy, układ i punkty montażowe zostają); reguły wentylacji - po Zastosuj."""
        tpl = getattr(self, '_enc_templates', {}).get(key)
        if tpl is None or self.mode != 'enclosure':
            return
        name, desc, params, rules = tpl
        current = self.enc_spec()
        spec = lib.template_spec(params, current.sources, current.frame)
        spec.mounts = current.mounts
        notes = []
        if self.enc.get('env') is not None:
            spec.envelope = self.enc['env']
            try:
                notes = lib.fit_template(spec, self.enc['env'], self.document.bodies)
            except kernel.CadError as e:
                notes = [str(e)]
        mounts_before = list(self.enc.get('mounts') or [])
        face = self.enc.get('face')
        self._enc_load_spec(spec)
        self.enc['mounts'] = mounts_before
        self.enc['face'] = face
        self.enc['rules'] = list(rules)
        self._enc_mounts_show()
        extra = f' Po Zastosuj: {len(rules)} reguł wentylacji.' if rules else ''
        self.enc_tpl_info.setText(f'{name}: {desc}{extra}' + (' ' + ' '.join(notes) if notes else ''))
        self._enc_update()

    def enc_template_save(self, name=None, folder=None):
        if self.mode != 'enclosure':
            return None
        if name is None:
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, 'Zapisz szablon obudowy', 'Nazwa szablonu:')
            if not ok or not name.strip():
                return None
        try:
            path = lib.save_user(name.strip(), self.enc_spec(), self.enc.get('rules') or [], folder)
        except OSError as e:
            self.toast(f'Nie udało się zapisać szablonu: {e}', 5000)
            return None
        self._enc_tpl_fill(f'user:{path.stem}')
        self.toast(f'Zapisano szablon „{name.strip()}”.', 4000)
        return path

    def _enc_apply_rules(self, made, rules):
        """Po utworzeniu obudowy: reguły szablonu (wentylacja) jako osobne kroki historii (każdy edytowalny i cofalny)."""
        if not rules or not made:
            return
        existing = list(self.document.bodies)
        seq0 = len(self.document.states())

        def build():
            return lib.apply_rules(existing, made, rules, seq0)

        def apply(value):
            _bodies, steps, warnings = value
            for recipe, bodies in steps:
                self.document.pending_op = recipe
                self.document.pending_label = 'Wentylacja (szablon)'
                self.document.pending_icon = 'encvent'
                self.document.commit(bodies)
            self._enc_rule_warnings = warnings
            if warnings:
                self.toast(' '.join(warnings), 7000)

        self.run_operation('Wentylacja (szablon)', build, apply)

    # ------------------------------------------------------------------ zestawienie i eksport (Kontrola obudowy)
    def _build_enc_export(self, lay):
        from . import shell_ui as ui
        lay.addWidget(ui.StepRow(3, 'x_enccheck', 'Zestawienie i eksport', plain=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        self.chk_material = QComboBox()
        for name, rho in lib.DENSITIES.items():
            self.chk_material.addItem(name, rho)
        self.chk_density = QDoubleSpinBox()
        self.chk_density.setRange(.01, 30)
        self.chk_density.setDecimals(3)
        self.chk_density.setSuffix(' g/cm³')
        self.chk_density.setValue(lib.DENSITIES['PLA'])
        self.chk_material.currentIndexChanged.connect(lambda *_: self.chk_density.setValue(float(self.chk_material.currentData())))
        self.chk_density.valueChanged.connect(lambda *_: self._chk_summary_update())
        grid.addWidget(_label('Materiał', 'label'), 0, 0)
        grid.addWidget(self.chk_material, 0, 1)
        grid.addWidget(_label('Gęstość', 'label'), 1, 0)
        grid.addWidget(self.chk_density, 1, 1)
        self.chk_infill = QDoubleSpinBox()
        self.chk_infill.setRange(0, 100)
        self.chk_infill.setDecimals(0)
        self.chk_infill.setSuffix(' %')
        self.chk_infill.setValue(100)
        self.chk_infill.setToolTip('Druk 3D: wypełnienie wnętrza ścianek (100 % = pełny materiał)')
        self.chk_shell = QDoubleSpinBox()
        self.chk_shell.setRange(0, 20)
        self.chk_shell.setDecimals(2)
        self.chk_shell.setSuffix(' mm')
        self.chk_shell.setValue(1.2)
        self.chk_shell.setToolTip('Druk 3D: łączna grubość obrysów przy każdej powierzchni')
        for box in (self.chk_infill, self.chk_shell):
            box.valueChanged.connect(lambda *_: self._chk_summary_update())
        grid.addWidget(_label('Wypełnienie druku', 'label'), 2, 0)
        grid.addWidget(self.chk_infill, 2, 1)
        grid.addWidget(_label('Grubość obrysów', 'label'), 3, 0)
        grid.addWidget(self.chk_shell, 3, 1)
        lay.addLayout(grid)
        self.chk_props = _label('', 'value')
        self.chk_props.setWordWrap(True)
        lay.addWidget(self.chk_props)
        fmt = QGridLayout()
        self.chk_formats = {}
        for n, (key, title) in enumerate(FORMATS):
            box = QCheckBox(title)
            box.setChecked(True)
            self.chk_formats[key] = box
            fmt.addWidget(box, n // 3, n % 3)
        lay.addLayout(fmt)
        self.chk_export = QPushButton('Eksportuj do folderu…')
        self.chk_export.setToolTip('STEP (części i całość), STL, 3MF, DXF (rozwinięcia / płyty), SVG (kontury), zestawienie CSV i TXT')
        self.chk_export.clicked.connect(lambda _=False: self.enc_export())
        lay.addWidget(self.chk_export)

    def _chk_summary_update(self):
        target = getattr(self, 'chk_target', None)
        body = self.document.get(target or '')
        on = body is not None and bool((body.meta or {}).get('enclosure'))
        self.chk_export.setEnabled(on)
        if not on:
            self.chk_props.setText('')
            return
        try:
            rows, total = lib.summary(self.document.bodies, target, float(self.chk_density.value()), float(self.chk_infill.value()),
                                      float(self.chk_shell.value()))
        except (kernel.CadError, Exception) as e:                  # zestawienie nie może zablokować okna kontroli
            self.chk_props.setText(f'Zestawienie niedostępne: {e}')
            return
        lines = [f'{r["name"]}: {r["dims"][0]:.1f} × {r["dims"][1]:.1f} × {r["dims"][2]:.1f} mm, {r["volume"] / 1000:.2f} cm³, '
                 f'{r["area"] / 100:.1f} cm², ~{r["mass"]:.1f} g' for r in rows]
        lines.append(f'Razem: {total["volume"] / 1000:.2f} cm³ objętości części, {total["material"] / 1000:.2f} cm³ materiału, '
                     f'szacunkowa masa ~{total["mass"]:.1f} g')
        self.chk_props.setText('\n'.join(lines))
        self.chk_summary = (rows, total)

    def enc_export(self, folder=None, formats=None):
        target = getattr(self, 'chk_target', None)
        if not target or self.document.get(target) is None:
            self.toast('Kliknij obudowę do eksportu.')
            return
        if folder is None:
            from PySide6.QtWidgets import QFileDialog
            folder = QFileDialog.getExistingDirectory(self, 'Folder eksportu obudowy')
            if not folder:
                return
        formats = tuple(formats or [k for k, b in self.chk_formats.items() if b.isChecked()])
        bodies = list(self.document.bodies)
        density, material = float(self.chk_density.value()), self.chk_material.currentText()
        infill, shell = float(self.chk_infill.value()), float(self.chk_shell.value())

        def compute():
            return lib.export(bodies, target, folder, density, material, formats, infill, shell)

        def show(files, error):
            if error:
                self.toast(f'Eksport nie powiódł się: {error}', 6000)
                return
            self._enc_exported = files
            self.toast(f'Zapisano {len(files)} plików w {folder}.', 5000)

        self.run_preview('enc_export', compute, show)
