"""Generator obudów - etap 22 (okno): „Dopasowanie przestrzenne 3D” (Obudowy → Dopasowanie 3D).

Kliknięcia brył wybierają komponenty (kliknięcie części obudowy dodaje jej elementy źródłowe). Tryb wybiera algorytm;
program nigdy nie zmienia go sam - gdy wybrany algorytm zawiedzie, zostaje ostatni poprawny wynik i komunikat.
Podgląd liczony w tle (Przerwij), Zastosuj / Enter - krok historii 'enc_fit' (edycja, cofanie, przeliczanie po zmianie
komponentów: wejście kroku to identyfikatory komponentów)."""
from __future__ import annotations

import uuid

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QListWidget, QPushButton, QTableWidget, QTableWidgetItem

from . import enclosure_fit as ef
from . import kernel
from . import shell_ui as ui
from .enclosure_ui import _label, _spin

_CANCEL = {'flag': False}
MODES = ef.FIT_MODES
MODE_LABELS = {'zone': 'Analiza i strefa ochronna (22A)', 'hull': 'Otoczka wypukła 3D (22B)', 'sections': 'Zmienny przekrój - loft przekrojów (22C)',
               'organic': 'Powierzchnie organiczne B-spline (22D)'}
AXES = {'z': [0, 0, 1.0], 'x': [1.0, 0, 0], 'y': [0, 1.0, 0]}
AXIS_LABELS = {'z': 'Oś obudowy: Z (stoi na dnie)', 'x': 'Oś obudowy: X', 'y': 'Oś obudowy: Y', 'pca': 'Oś obudowy: najdłuższa oś komponentów'}
# pole: (tytuł, wartość, min, max, miejsca, krok, jednostka, tryby)
FIELDS = (('clearance', 'Odstęp (strefa ochronna)', 2.0, 0.0, 200.0, 2, .5, ' mm', MODES),
          ('wall', 'Grubość ścianki', 2.0, .2, 50.0, 2, .5, ' mm', MODES[1:]),
          ('wall_bottom', 'Dodatkowa grubość dna', 0.0, 0.0, 50.0, 2, .5, ' mm', MODES[1:]),
          ('wall_top', 'Dodatkowa grubość pokrywy', 0.0, 0.0, 50.0, 2, .5, ' mm', MODES[1:]),
          ('directions', 'Dokładność otoczki (kierunki)', 160, 26, 2000, 0, 10, '', ('hull',)),
          ('sections', 'Liczba przekrojów', 8, 2, 200, 0, 1, '', ('sections',)),
          ('corner', 'Zaokrąglenie przekroju', 2.0, .2, 100.0, 2, .5, ' mm', ('sections',)),
          ('smooth', 'Wygładzenie', 4.0, 0.0, 200.0, 2, .5, ' mm', ('organic',)),
          ('nu', 'Punkty obwodu B-spline', 36, 12, 400, 0, 2, '', ('organic',)),
          ('nv', 'Punkty wzdłuż osi B-spline', 10, 4, 200, 0, 1, '', ('organic',)),
          ('split_at', 'Podział (wysokość wnętrza)', 50.0, 5.0, 95.0, 1, 1.0, ' %', MODES[1:]),
          ('lip', 'Wysokość zakładki', 3.0, .5, 50.0, 2, .5, ' mm', MODES[1:]),
          ('lip_gap', 'Luz zakładki', .2, 0.0, 5.0, 2, .05, ' mm', MODES[1:]))
COMBOS = (('zone_mode', ef.ZONE_LABELS, MODES), ('axis', AXIS_LABELS, MODES[1:]), ('section', ef.SECTION_LABELS, ('sections',)),
          ('disjoint', ef.DISJOINT_LABELS, ('sections',)), ('wall_method', ef.WALL_LABELS, MODES[1:]), ('joint', ef.JOINT_LABELS, MODES[1:]))
INTS = ('directions', 'sections', 'nu', 'nv')


def components_of(bodies, ids):
    by_id = {b.id: b for b in bodies}
    out = []
    for i in ids:
        b = by_id.get(i)
        if b is None:
            raise kernel.CadError('Komponentu wybranego do dopasowania już nie ma.')
        out.append((b.id, b.name, b.shape))
    return out


def _axis(p, comps):
    key = p.get('axis_key') or 'z'
    if key == 'pca':
        import numpy as np
        from .enclosure_optimize import _points
        pts = np.vstack([_points(sh) for _i, _n, sh in comps])
        return [float(v) for v in ef._pca(pts)[1][0]]
    return AXES.get(key, AXES['z'])


def build(bodies, recipe, cancel=None):
    p = dict(ef.DEFAULTS, **recipe['params'])
    comps = components_of(bodies, recipe['sources'])
    p['axis'] = _axis(p, comps)
    return ef.fit(comps, p, cancel)


def run(bodies, recipe):
    """Krok 'enc_fit': wynik dopasowania jako osobne bryły (identyfikatory z przepisu); komponenty bez zmian. Wynik
    z błędem walidacji nie jest zapisywany (zostaje poprzednia geometria)."""
    import cadquery as cq
    from .document import Body
    res = build(bodies, recipe)
    errors = [t for l, t in res['report'] if l == 'error']
    if errors:
        raise kernel.CadError('Dopasowanie nie przeszło kontroli: ' + '; '.join(errors[:3]))
    ids = list(recipe.get('out_ids') or [])
    while len(ids) < len(res['parts']):
        ids.append(uuid.uuid4().hex)
    old = set(recipe.get('out_ids') or [])
    recipe['out_ids'] = ids[:len(res['parts'])]
    info = {k: recipe[k] for k in recipe if k != 'type'}
    out = [b for b in bodies if b.id not in old]
    folder = recipe['params'].get('name') or ('Obudowa 3D' if recipe['params'].get('mode', 'zone') != 'zone' else '')
    for n, (name, shape) in enumerate(res['parts']):
        out.append(Body(name, cq.Shape.cast(shape), id=ids[n], color=(.55, .8, .95) if recipe['params'].get('mode', 'zone') == 'zone' else None,
                        folder=folder if len(res['parts']) > 1 else '', meta=dict(enclosure_fit=info, enclosure_fit_part=n)).prepared())
    return out


class EnclosureFitTools:
    def _build_encfit_panel(self):
        self.ft = dict(ids=[], result=None)
        self._ft_timer = QTimer(self)
        self._ft_timer.setSingleShot(True)
        self._ft_timer.setInterval(500)
        self._ft_timer.timeout.connect(lambda: self._ft_exact())
        self.ft_panel, lay = self._panel(320, 'Dopasowanie przestrzenne 3D', 'x_encfit', 'Komponenty → strefa → obudowa', plain=True, scroll=True)
        self.ft_step1 = ui.StepRow(1, 'x_enclosure', 'Komponenty', plain=True)
        lay.addWidget(self.ft_step1)
        self.ft_step2 = ui.StepRow(2, 'x_encfit', 'Tryb i parametry', plain=True)
        lay.addWidget(self.ft_step2)
        self.ft_mode = QComboBox()
        for k_ in MODES:
            self.ft_mode.addItem(MODE_LABELS[k_], k_)
        self.ft_mode.currentIndexChanged.connect(lambda *_: self._ft_update())
        lay.addWidget(self.ft_mode)
        self.ft_c, self.ft_f, self.ft_rows = {}, {}, []
        for key, items, modes in COMBOS:
            box = QComboBox()
            for k_, title in items.items():
                box.addItem(title, k_)
            box.currentIndexChanged.connect(lambda *_: self._ft_update())
            lay.addWidget(box)
            self.ft_c[key] = box
            self.ft_rows.append((modes, [box]))
        self.ft_split = QCheckBox('Podział na podstawę i pokrywę (22E)')
        self.ft_split.toggled.connect(lambda *_: self._ft_update())
        lay.addWidget(self.ft_split)
        self.ft_rows.append((MODES[1:], [self.ft_split]))
        grid = QGridLayout()
        for n, (key, title, val, lo, hi, dec, step, suf, modes) in enumerate(FIELDS):
            box = _spin(float(val), float(lo), float(hi), dec, step, suf)
            box.valueChanged.connect(lambda *_: self._ft_update())
            lab = _label(title, 'label')
            grid.addWidget(lab, n, 0)
            grid.addWidget(box, n, 1)
            self.ft_f[key] = box
            self.ft_rows.append((modes, [lab, box]))
        lay.addLayout(grid)
        self.ft_st_label = _label('Przekroje edytowane (położenie 0-100 %, dodatkowe odsunięcie mm; puste = równomiernie):', 'label')
        self.ft_st_label.setWordWrap(True)
        lay.addWidget(self.ft_st_label)
        self.ft_st = QTableWidget(0, 2)
        self.ft_st.setHorizontalHeaderLabels(['Położenie %', 'Odsunięcie mm'])
        self.ft_st.setFixedHeight(110)
        self.ft_st.itemChanged.connect(lambda *_: self._ft_update())
        lay.addWidget(self.ft_st)
        row = QHBoxLayout()
        add = QPushButton('Dodaj przekrój')
        add.clicked.connect(lambda _=False: self._ft_station_add())
        rem = QPushButton('Usuń przekrój')
        rem.clicked.connect(lambda _=False: self._ft_station_remove())
        row.addWidget(add)
        row.addWidget(rem)
        lay.addLayout(row)
        self.ft_rows.append((('sections',), [self.ft_st_label, self.ft_st, add, rem]))
        self.ft_list = QListWidget()
        self.ft_list.setObjectName('enclist')
        self.ft_list.setFixedHeight(80)
        lay.addWidget(self.ft_list)
        stop = QPushButton('Przerwij obliczenia')
        stop.clicked.connect(lambda _=False: _CANCEL.update(flag=True))
        lay.addWidget(stop)
        self.ft_info = _label('', 'value')
        self.ft_info.setWordWrap(True)
        lay.addWidget(self.ft_info)
        self.ft_status = _label('Kliknij komponenty (albo część obudowy - jej elementy).', 'status')
        lay.addWidget(self.ft_status)
        self.ft_apply, _ = self._buttons(self.ft_panel.footer, 'Zastosuj', 'Anuluj', self.apply_encfit, lambda: self.set_mode(None))
        return self.ft_panel

    def _encfit_begin(self):
        self.ft = dict(ids=[], result=None)
        self.ft_panel.show()
        self.hint('Dopasowanie 3D: klikaj komponenty (kliknięcie części obudowy dodaje jej elementy), potem Zastosuj.')
        self.view.setCursor(Qt.PointingHandCursor)
        self._ft_update()

    def encfit_hover(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        self.view.set_hover_mesh(body.mesh if body is not None and body.kind in ('solid', 'mesh') else None)

    def encfit_click(self, x, y, shift=False):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind not in ('solid', 'mesh') or (body.meta or {}).get('enclosure_fit'):
            return
        if (body.meta or {}).get('enclosure'):
            from .enclosure import EnclosureSpec
            for s in EnclosureSpec.from_json(body.meta['enclosure']).sources:
                if s.id not in self.ft['ids'] and self.document.get(s.id) is not None:
                    self.ft['ids'].append(s.id)
        elif body.id in self.ft['ids']:
            self.ft['ids'].remove(body.id)
        else:
            self.ft['ids'].append(body.id)
        self._ft_update()

    def _ft_station_add(self):
        r = self.ft_st.rowCount()
        self.ft_st.blockSignals(True)
        self.ft_st.insertRow(r)
        self.ft_st.setItem(r, 0, QTableWidgetItem('50'))
        self.ft_st.setItem(r, 1, QTableWidgetItem('0'))
        self.ft_st.blockSignals(False)
        self._ft_update()

    def _ft_station_remove(self):
        r = self.ft_st.currentRow() if self.ft_st.currentRow() >= 0 else self.ft_st.rowCount() - 1
        if r >= 0:
            self.ft_st.removeRow(r)
            self._ft_update()

    def ft_stations(self):
        out = []
        for r in range(self.ft_st.rowCount()):
            try:
                t = float((self.ft_st.item(r, 0).text() if self.ft_st.item(r, 0) else '').replace(',', '.')) / 100.0
                off = float((self.ft_st.item(r, 1).text() if self.ft_st.item(r, 1) else '0').replace(',', '.') or 0)
            except ValueError:
                continue
            out.append(dict(t=min(1.0, max(0.0, t)), offset=off))
        return out

    def ft_params(self):
        out = dict(mode=self.ft_mode.currentData(), **{k_: float(b.value()) for k_, b in self.ft_f.items()})
        for k_ in INTS:
            out[k_] = int(out[k_])
        for k_, box in self.ft_c.items():
            out['axis_key' if k_ == 'axis' else k_] = box.currentData()
        out['split'] = self.ft_split.isChecked()
        st = self.ft_stations()
        if st:
            out['stations'] = st
        return out

    def ft_recipe(self):
        if not self.ft['ids']:
            return None
        return dict(type='enc_fit', sources=list(self.ft['ids']), params=self.ft_params(), out_ids=list(self.ft.get('out_ids') or []))

    def _ft_update(self):
        if not hasattr(self, 'ft_f') or self.mode != 'encfit':
            return
        self.ft_list.clear()
        for i in self.ft['ids']:
            b = self.document.get(i)
            self.ft_list.addItem(b.name if b is not None else i)
        mode = self.ft_mode.currentData()
        for modes, widgets in self.ft_rows:                            # tylko parametry wybranego trybu
            for w_ in widgets:
                w_.setVisible(mode in modes)
        n = len(self.ft['ids'])
        self.ft_step1.set_state('done' if n else 'active', f'{n} komponent(y)' if n else 'kliknij bryły')
        self.ft_step2.set_state('active' if n else 'pending', MODE_LABELS[self.ft_mode.currentData()])
        self.ft_apply.setEnabled(False)
        self._ft_timer.stop()
        if not n:
            self.view.set_preview_mesh(None)
            return
        self.ft_status.setText('Liczenie…')
        self._ft_timer.start()

    def _ft_exact(self):
        recipe = self.ft_recipe()
        if recipe is None or self.mode != 'encfit':
            return
        sig = repr(recipe)
        self._ft_sig = sig
        bodies = list(self.document.bodies)
        _CANCEL['flag'] = False

        def compute():
            import cadquery as cq
            from .enclosure import merge_meshes
            res = build(bodies, recipe, cancel=lambda: _CANCEL['flag'])
            return dict(mesh=merge_meshes([kernel.display_mesh(cq.Shape.cast(s)) for _n, s in res['parts']]), report=res['report'])

        def show(value, error):
            if self.mode != 'encfit' or getattr(self, '_ft_sig', None) != sig:
                return
            if error or value is None:                                 # ostatni poprawny wynik zostaje w podglądzie
                self.ft_status.setText((str(error) if error else 'Nie udało się.') + (' Podgląd: ostatni poprawny wynik.' if self.ft.get('result') else ''))
                return
            bad = [t for l, t in value['report'] if l == 'error']
            self.ft_info.setText('\n'.join(t for _l, t in value['report']))
            if bad:                                                    # wynik z błędem: zostaje ostatni poprawny podgląd
                self.ft_status.setText('Wynik nie przeszedł kontroli - ' + bad[0] + (' Podgląd: ostatni poprawny wynik.' if self.ft.get('result') else ''))
                self.ft_apply.setEnabled(False)
                return
            self.ft['result'] = value
            self.view.set_preview_mesh(value['mesh'], color=(.45, .75, .95, .35), line_color=(.1, .35, .6, 1), width=1.2)
            self.ft_status.setText('Enter albo Zastosuj dodaje wynik.')
            self.ft_apply.setEnabled(True)
        self.run_preview('encfit', compute, show)

    def _step_fill_enc_fit(self, recipe):
        p = dict(ef.DEFAULTS, **recipe['params'])
        self.ft.update(ids=list(recipe['sources']), out_ids=list(recipe.get('out_ids') or []))
        self.ft_mode.blockSignals(True)
        self.ft_mode.setCurrentIndex(max(0, self.ft_mode.findData(p.get('mode', 'zone'))))
        self.ft_mode.blockSignals(False)
        for k_, box in self.ft_c.items():
            val = p.get('axis_key' if k_ == 'axis' else k_)
            if val is not None:
                box.blockSignals(True)
                box.setCurrentIndex(max(0, box.findData(val)))
                box.blockSignals(False)
        for k_, box in self.ft_f.items():
            if k_ in p:
                box.blockSignals(True)
                box.setValue(float(p[k_]))
                box.blockSignals(False)
        self.ft_split.blockSignals(True)
        self.ft_split.setChecked(bool(p.get('split')))
        self.ft_split.blockSignals(False)
        self.ft_st.blockSignals(True)
        self.ft_st.setRowCount(0)
        for q in p.get('stations') or []:
            r = self.ft_st.rowCount()
            self.ft_st.insertRow(r)
            self.ft_st.setItem(r, 0, QTableWidgetItem(f'{100 * float(q["t"]):g}'))
            self.ft_st.setItem(r, 1, QTableWidgetItem(f'{float(q.get("offset", 0)):g}'))
        self.ft_st.blockSignals(False)
        self._ft_update()

    def apply_encfit(self):
        if self.busy or self.mode != 'encfit' or not self.ft_apply.isEnabled():
            return
        recipe = self.ft_recipe()
        editing = (getattr(self, '_step_edit', None) or {}).get('recipe') or {}
        same = editing.get('type') == recipe['type']
        recipe['id'] = editing.get('id') if same and editing.get('id') else uuid.uuid4().hex
        recipe['out_ids'] = list(editing.get('out_ids') or []) if same else []
        existing = list(self.document.bodies)

        def build_step():
            return run(existing, recipe)

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Dopasowanie przestrzenne 3D'
            self.document.pending_icon = 'encfit'
            self.document.commit(bodies)

        def after():
            self.view.set_preview_mesh(None)
            self.ft.update(ids=[], result=None, out_ids=[])
            self._ft_update()

        self._ft_timer.stop()
        self.view.set_preview_mesh(None)
        self.run_operation('Dopasowanie przestrzenne 3D', build_step, apply, after=after)
