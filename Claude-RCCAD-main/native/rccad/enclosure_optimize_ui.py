"""Generator obudów - etap 21 (okno): „Optymalizacja obudowy” (Obudowy → Optymalizacja).

Kliknięcie części obudowy → tryb (A: tylko obudowa, B: także rozmieszczenie - propozycja), cele z wagami, ograniczenia
(blokady komponentów, na dnie, zespoły, dostęp do złącza, strefy serwisowe, strefy zabronione, zablokowane ścianki,
odstęp, maks. wymiary, dozwolone obroty), dokładność, limit czasu. Szukaj liczy w tle z postępem i przyciskiem Przerwij;
lista najlepszych wariantów z porównaniem (wymiary, objętość, materiał, masa, % zmiany, przesunięte / obrócone, wynik
kontroli kolizji) i podglądem - przełączanie wariantów nie zmienia dokumentu. Zastosuj - jeden krok historii 'enc_opt'
(jedno Cofnij): komponenty przeniesione, obudowa przebudowana z otworami, wentylacją i innymi operacjami."""
from __future__ import annotations

import uuid

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLineEdit, QListWidget, QProgressBar, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem)

from . import enclosure as enc
from . import enclosure_optimize as eo
from . import kernel
from . import shell_ui as ui
from .enclosure_ui import _label, _spin

_STATE = {'cancel': False, 'progress': 0.0, 'best': None}
ACCESS = ('', 'x-', 'x+', 'y-', 'y+', 'z+')
ACCESS_LABELS = {'': '—', 'x-': 'X-', 'x+': 'X+', 'y-': 'Y-', 'y+': 'Y+', 'z+': 'Z+ (góra)'}
_DIR = {'x-': (-1, 0, 0), 'x+': (1, 0, 0), 'y-': (0, -1, 0), 'y+': (0, 1, 0), 'z-': (0, 0, -1), 'z+': (0, 0, 1)}


def _part(bodies, target):
    by_id = {b.id: b for b in bodies}
    part = by_id.get(target)
    if part is None or part.kind != 'solid' or not (part.meta or {}).get('enclosure'):
        raise kernel.CadError('Części obudowy do optymalizacji już nie ma.')
    return part, enc.EnclosureSpec.from_json(part.meta['enclosure'])


def problem_data(bodies, target, table):
    """Dane wejściowe przeszukiwania z dokumentu: items, shapes, osie obudowy, odstępy, ścianki, przewody."""
    from .enclosure_cable_ui import endpoint
    from .enclosure_param import group
    part, spec = _part(bodies, target)
    by_id = {b.id: b for b in bodies}
    items, shapes = [], {}
    for s in spec.sources:
        b = by_id.get(s.id)
        if b is None or b.kind not in ('solid', 'mesh'):
            continue
        row = (table or {}).get(b.id) or {}
        E = np.asarray(spec.envelope.axes, float)
        it = dict(id=b.id, name=b.name, points=eo._points(b.shape), lock=bool(row.get('lock')), floor=bool(row.get('floor')),
                  group=row.get('group') or '')
        if row.get('access'):
            it['access'] = [list(E.T @ np.asarray(_DIR[row['access']], float))]          # kierunek w układzie obudowy → świat
        if row.get('service_dir') and float(row.get('service', 0)) > 0:
            it['service'] = [(list(E.T @ np.asarray(_DIR[row['service_dir']], float)), float(row['service']))]
        items.append(it)
        shapes[b.id] = b.shape
    if not items:
        raise kernel.CadError('Obudowa nie ma komponentów (elementów źródłowych) do optymalizacji.')
    cables = []
    for b in group(bodies, part):
        for r in (b.meta or {}).get('enclosure_cables', []):
            try:
                pa, _d = endpoint(bodies, r['start'])
                pb, _d = endpoint(bodies, r['end'])
            except Exception:
                continue
            cables.append((list(pa), (r['start'] or {}).get('comp'), list(pb), (r['end'] or {}).get('comp')))
    return items, shapes, np.asarray(spec.envelope.axes, float), enc.clearance_of(spec), enc.walls_of(spec), cables


def run(bodies, recipe):
    """Krok 'enc_opt': zatwierdzony wariant - komponenty przeniesione (macierze z przepisu), dla trybu A obrócony układ
    obudowy; potem przebudowa obudowy z jej operacjami (enclosure_param.regenerate)."""
    from dataclasses import replace
    from .enclosure_param import group, regenerate
    part, spec = _part(bodies, recipe['target'])
    out = []
    for b in bodies:
        tr = (recipe.get('transforms') or {}).get(b.id)
        if tr:
            R, t = np.asarray(tr['R'], float), np.asarray(tr['t'], float)
            if abs(np.linalg.det(R) - 1) > 1e-6:
                raise kernel.CadError('Niepoprawna macierz obrotu w przepisie optymalizacji.')
            b = b.placed(kernel.transformed(b.shape, R, t), np.hstack([R, t[:, None]])).prepared()
        out.append(b)
    if recipe.get('axes') and recipe.get('mode') == 'A':
        ids = {g.id for g in group(out, next(x for x in out if x.id == part.id))}
        new = []
        for b in out:
            if b.id in ids:
                sp = enc.EnclosureSpec.from_json(b.meta['enclosure'])
                sp.frame = enc.FrameSpec(mode='axes', face=dict(axes=[list(map(float, a)) for a in recipe['axes']]))
                b = replace(b, meta=dict(b.meta, enclosure=sp.to_json()))
            new.append(b)
        out = new
    return regenerate(out, dict(type='enc_regen', id=part.id))


def _rigid(mesh, R, t):
    R, t = np.asarray(R, float), np.asarray(t, float)
    return kernel.DisplayMesh((np.asarray(mesh.vertices, float) @ R.T + t).astype(np.float32), mesh.triangles,
                              {k_: (np.asarray(v, float) @ R.T + t).astype(np.float32) for k_, v in mesh.edges.items()},
                              tuple(np.asarray(mesh.center, float) @ R.T + t), mesh.size)


class EnclosureOptimizeTools:
    def _build_encopt_panel(self):
        self.op = dict(target=None, result=None, sel=None)
        self._op_timer = QTimer(self)
        self._op_timer.setInterval(250)
        self._op_timer.timeout.connect(lambda: self._op_poll())
        self.op_panel, lay = self._panel(340, 'Optymalizacja obudowy', 'x_encopt', 'Cele → ograniczenia → warianty', plain=True, scroll=True)
        self.op_step1 = ui.StepRow(1, 'x_enclosure', 'Część obudowy', plain=True)
        lay.addWidget(self.op_step1)
        self.op_step2 = ui.StepRow(2, 'x_encopt', 'Cele i ograniczenia', plain=True)
        lay.addWidget(self.op_step2)
        self.op_mode = QComboBox()
        self.op_mode.addItem('Tryb A: tylko obudowa (komponenty bez zmian)', 'A')
        self.op_mode.addItem('Tryb B: także rozmieszczenie komponentów (propozycja)', 'B')
        self.op_mode.currentIndexChanged.connect(lambda *_: self._op_changed())
        lay.addWidget(self.op_mode)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        self.op_w = {}
        for n, g in enumerate(eo.GOALS):
            box = _spin(1.0 if g == 'volume' else 0.0, 0.0, 10.0, 2, .25, '')
            box.valueChanged.connect(lambda *_: self._op_changed())
            grid.addWidget(_label(eo.GOAL_LABELS[g], 'label'), n, 0)
            grid.addWidget(box, n, 1)
            self.op_w[g] = box
        r0 = len(eo.GOALS)
        self.op_f = {}
        for n, (key, title, val, hi, suf) in enumerate((('density', 'Gęstość materiału', 1.24, 30.0, ' g/cm³'), ('gap', 'Odstęp między komponentami', 2.0, 100.0, ' mm'),
                                                        ('max_x', 'Maks. wymiar X (0 = bez)', 0.0, 1e4, ' mm'), ('max_y', 'Maks. wymiar Y (0 = bez)', 0.0, 1e4, ' mm'),
                                                        ('max_z', 'Maks. wymiar Z (0 = bez)', 0.0, 1e4, ' mm'), ('time', 'Limit czasu', 10.0, 600.0, ' s'))):
            box = _spin(val, 0.0, hi, 2, .5, suf)
            box.valueChanged.connect(lambda *_: self._op_changed())
            grid.addWidget(_label(title, 'label'), r0 + n, 0)
            grid.addWidget(box, r0 + n, 1)
            self.op_f[key] = box
        self.op_top = QSpinBox()
        self.op_top.setRange(1, 20)
        self.op_top.setValue(5)
        grid.addWidget(_label('Liczba najlepszych wariantów', 'label'), r0 + 6, 0)
        grid.addWidget(self.op_top, r0 + 6, 1)
        lay.addLayout(grid)
        self.op_c = {}
        for key, items in (('rotations', eo.ROTATION_LABELS), ('enc_rotation', eo.ENC_ROT_LABELS), ('accuracy', eo.ACCURACY_LABELS)):
            box = QComboBox()
            for k_, title in items.items():
                box.addItem(title, k_)
            box.currentIndexChanged.connect(lambda *_: self._op_changed())
            lay.addWidget(box)
            self.op_c[key] = box
        self.op_c['accuracy'].setCurrentIndex(1)
        row = QHBoxLayout()
        row.addWidget(_label('Zablokowane ścianki:', 'label'))
        self.op_walls = {}
        for s in eo.SIDES:
            cb_ = QCheckBox(s)
            cb_.toggled.connect(lambda *_: self._op_changed())
            row.addWidget(cb_)
            self.op_walls[s] = cb_
        lay.addLayout(row)
        self.op_forbid = QLineEdit('')
        self.op_forbid.setPlaceholderText('Strefy zabronione: x0 y0 z0 x1 y1 z1; kolejna; …')
        self.op_forbid.editingFinished.connect(lambda: self._op_changed())
        lay.addWidget(self.op_forbid)
        lay.addWidget(_label('Komponenty:', 'label'))
        self.op_table = QTableWidget(0, 6)
        self.op_table.setHorizontalHeaderLabels(['Nazwa', 'Blokada', 'Na dnie', 'Zespół', 'Złącze przy ściance', 'Strefa serwisowa'])
        self.op_table.setFixedHeight(150)
        self.op_table.itemChanged.connect(lambda *_: self._op_changed())
        lay.addWidget(self.op_table)
        row = QHBoxLayout()
        self.op_go = QPushButton('Szukaj wariantów')
        self.op_go.clicked.connect(lambda _=False: self.encopt_search())
        row.addWidget(self.op_go)
        stop = QPushButton('Przerwij')
        stop.clicked.connect(lambda _=False: _STATE.update(cancel=True))
        row.addWidget(stop)
        lay.addLayout(row)
        self.op_bar = QProgressBar()
        self.op_bar.setRange(0, 100)
        lay.addWidget(self.op_bar)
        self.op_list = QListWidget()
        self.op_list.setObjectName('enclist')
        self.op_list.setFixedHeight(110)
        self.op_list.currentRowChanged.connect(lambda r: self._op_select(r))
        lay.addWidget(self.op_list)
        self.op_info = _label('', 'value')
        self.op_info.setWordWrap(True)
        lay.addWidget(self.op_info)
        self.op_status = _label('Kliknij część obudowy.', 'status')
        lay.addWidget(self.op_status)
        self.op_apply, _ = self._buttons(self.op_panel.footer, 'Zastosuj', 'Anuluj', self.apply_encopt, lambda: self.set_mode(None))
        return self.op_panel

    def _encopt_begin(self):
        self.op = dict(target=None, result=None, sel=None)
        self.op_panel.show()
        self.op_table.setRowCount(0)
        self.op_list.clear()
        self.hint('Optymalizacja obudowy: kliknij część obudowy, ustaw cele i ograniczenia, Szukaj wariantów.')
        self.view.setCursor(Qt.PointingHandCursor)
        self._op_changed()

    def encopt_hover(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        self.view.set_hover_mesh(body.mesh if body is not None and (body.meta or {}).get('enclosure') else None)

    def encopt_click(self, x, y, shift=False):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or not (body.meta or {}).get('enclosure') or body.kind != 'solid':
            self.toast('Kliknij część obudowy z Generatora obudów.')
            return
        self.encopt_target(body.id)

    def encopt_target(self, ident, table=None):
        self.op.update(target=ident, result=None, sel=None)
        spec = enc.EnclosureSpec.from_json(self.document.get(ident).meta['enclosure'])
        self.op_table.blockSignals(True)
        self.op_table.setRowCount(0)
        for s in spec.sources:
            b = self.document.get(s.id)
            if b is None:
                continue
            row = (table or {}).get(b.id) or {}
            r = self.op_table.rowCount()
            self.op_table.insertRow(r)
            name = QTableWidgetItem(b.name)
            name.setData(Qt.UserRole, b.id)
            name.setFlags(name.flags() & ~Qt.ItemIsEditable)
            self.op_table.setItem(r, 0, name)
            for col, key in ((1, 'lock'), (2, 'floor')):
                it = QTableWidgetItem('')
                it.setFlags((it.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
                it.setCheckState(Qt.Checked if row.get(key) else Qt.Unchecked)
                self.op_table.setItem(r, col, it)
            self.op_table.setItem(r, 3, QTableWidgetItem(row.get('group') or ''))
            box = QComboBox()
            for k_ in ACCESS:
                box.addItem(ACCESS_LABELS[k_], k_)
            box.setCurrentIndex(max(0, box.findData(row.get('access') or '')))
            box.currentIndexChanged.connect(lambda *_: self._op_changed())
            self.op_table.setCellWidget(r, 4, box)
            sv = QLineEdit(f'{row["service_dir"]} {float(row.get("service", 0)):g}' if row.get('service_dir') else '')
            sv.setPlaceholderText('np. y- 20')
            sv.editingFinished.connect(lambda: self._op_changed())
            self.op_table.setCellWidget(r, 5, sv)
        self.op_table.blockSignals(False)
        self._op_changed()

    def op_table_data(self):
        out = {}
        for r in range(self.op_table.rowCount()):
            ident = self.op_table.item(r, 0).data(Qt.UserRole)
            sv = self.op_table.cellWidget(r, 5).text().split() if self.op_table.cellWidget(r, 5) else []
            row = dict(lock=self.op_table.item(r, 1).checkState() == Qt.Checked, floor=self.op_table.item(r, 2).checkState() == Qt.Checked,
                       group=(self.op_table.item(r, 3).text() if self.op_table.item(r, 3) else '').strip(),
                       access=self.op_table.cellWidget(r, 4).currentData() if self.op_table.cellWidget(r, 4) else '')
            if len(sv) == 2 and sv[0] in _DIR:
                try:
                    row.update(service_dir=sv[0], service=float(sv[1].replace(',', '.')))
                except ValueError:
                    pass
            out[ident] = row
        return out

    def op_params(self):
        forb = []
        for chunk in self.op_forbid.text().split(';'):
            nums = chunk.replace(',', '.').split()
            if len(nums) == 6:
                try:
                    v = [float(x) for x in nums]
                except ValueError:
                    continue
                forb.append([[min(v[0], v[3]), min(v[1], v[4]), min(v[2], v[5])], [max(v[0], v[3]), max(v[1], v[4]), max(v[2], v[5])]])
        return dict(mode=self.op_mode.currentData(), weights={g: float(b.value()) for g, b in self.op_w.items() if b.value() > 0},
                    density=float(self.op_f['density'].value()), gap=float(self.op_f['gap'].value()),
                    max_dims=[float(self.op_f[k_].value()) for k_ in ('max_x', 'max_y', 'max_z')], time_limit=float(self.op_f['time'].value()),
                    top=self.op_top.value(), rotations=self.op_c['rotations'].currentData(), enc_rotation=self.op_c['enc_rotation'].currentData(),
                    accuracy=self.op_c['accuracy'].currentData(), locked_walls=[s for s, b in self.op_walls.items() if b.isChecked()], forbidden=forb)

    def _op_changed(self):
        if not hasattr(self, 'op_c') or self.mode != 'encopt':
            return
        tb = self.document.get(self.op.get('target') or '')
        self.op_step1.set_state('done' if tb else 'active', tb.name if tb else 'kliknij część')
        self.op_step2.set_state('active' if tb else 'pending', 'Szukaj wariantów' if tb else '')
        self.op['result'] = None
        self.op_list.clear()
        self.op_info.setText('')
        self.op_apply.setEnabled(False)
        self.view.set_preview_mesh(None)
        self.op_go.setEnabled(tb is not None)
        if tb is not None:
            self.op_status.setText('Ustaw cele i ograniczenia, potem Szukaj wariantów.')

    def encopt_search(self):
        if self.mode != 'encopt' or not self.op.get('target'):
            return
        bodies = list(self.document.bodies)
        target, table, p = self.op['target'], self.op_table_data(), self.op_params()
        sig = repr((target, table, p))
        self._op_sig = sig
        _STATE.update(cancel=False, progress=0.0, best=None)

        def compute():
            items, shapes, axes, clear, walls, cables = problem_data(bodies, target, table)
            res = eo.run_search(items, shapes, axes, clear, walls, p, cables, cancel=lambda: _STATE['cancel'],
                                progress=lambda f, b: _STATE.update(progress=f, best=b))
            res['table'], res['params'] = table, p
            return res

        def show(value, error):
            self._op_timer.stop()
            self.op_bar.setValue(100 if value else 0)
            if self.mode != 'encopt' or getattr(self, '_op_sig', None) != sig:
                return
            if error or value is None:
                self.op_status.setText(str(error) if error else 'Nie znaleziono wariantów.')
                return
            self.op['result'] = value
            self.op_list.blockSignals(True)
            self.op_list.clear()
            for n, v in enumerate(value['variants']):
                d = v['metrics']['dims']
                self.op_list.addItem(f'{n + 1}. {"poprawny" if v["exact"]["valid"] else "NIEPOPRAWNY"} · {d[0]:.1f} × {d[1]:.1f} × {d[2]:.1f} mm · '
                                     f'ocena {v["score"]:.3f} · objętość {v["change"]["volume"]:+.1f} %')
            self.op_list.blockSignals(False)
            self.op_status.setText(f'Przeszukanie: {value["seconds"]:.1f} s. Najlepszy znaleziony wariant (bez gwarancji optimum globalnego) - wybierz z listy.')
            if value['variants']:
                self.op_list.setCurrentRow(0)
        self.op_status.setText('Szukanie wariantów…')
        self.op_bar.setValue(0)
        self._op_timer.start()
        self.run_preview('encopt', compute, show)

    def _op_poll(self):
        self.op_bar.setValue(int(100 * float(_STATE.get('progress') or 0.0)))
        if _STATE.get('best') is not None:
            self.op_status.setText(f'Szukanie wariantów… najlepsza ocena dotąd {float(_STATE["best"]):.3f}')

    def _op_select(self, row):
        res = self.op.get('result')
        if res is None or not (0 <= row < len(res['variants'])):
            self.op_apply.setEnabled(False)
            return
        v = res['variants'][row]
        self.op['sel'] = row
        b, m = res['base'], v['metrics']
        lines = [f'Wymiary: {m["dims"][0]:.1f} × {m["dims"][1]:.1f} × {m["dims"][2]:.1f} mm (teraz {b["dims"][0]:.1f} × {b["dims"][1]:.1f} × {b["dims"][2]:.1f})',
                 f'Objętość: {m["volume"] / 1000:.1f} cm³ ({v["change"]["volume"]:+.1f} %), materiał: {m["material"] / 1000:.1f} cm³ ({v["change"]["material"]:+.1f} %)',
                 f'Masa: {m["mass"]:.1f} g ({v["change"]["mass"]:+.1f} %), powierzchnia {v["change"]["area"]:+.1f} %, przewody {v["change"]["cable"]:+.1f} %',
                 f'Przesunięte komponenty: {v["moved"]}, obrócone: {v["rotated"]}' + (f', obrót obudowy {v["angle"]:.2f}°' if v.get('angle') is not None else ''),
                 'Kontrola B-Rep: ' + ('bez kolizji, ograniczenia spełnione' if v['exact']['valid'] else '; '.join(t for _l, t in v['exact']['issues'][:4]))]
        self.op_info.setText('\n'.join(lines))
        self.op_apply.setEnabled(bool(v['exact']['valid']) and (bool(v['transforms']) or v.get('angle') is not None))
        meshes = []
        for ident, tr in v['transforms'].items():
            body = self.document.get(ident)
            if body is not None and body.mesh is not None:
                meshes.append(_rigid(body.mesh, tr['R'], tr['t']))
        try:
            meshes.append(kernel.display_mesh(enc.envelope_shape(v['env'])))
        except Exception:
            pass
        from .enclosure import merge_meshes
        self.view.set_preview_mesh(merge_meshes(meshes), color=(.3, .8, .45, .25) if v['exact']['valid'] else (.9, .3, .3, .3),
                                   line_color=(.1, .45, .2, 1) if v['exact']['valid'] else (.7, .1, .1, 1), width=1.4)

    def _step_fill_enc_opt(self, recipe):
        p = dict(eo.DEFAULTS, **recipe.get('params') or {})
        self.op_mode.blockSignals(True)
        self.op_mode.setCurrentIndex(max(0, self.op_mode.findData(p['mode'])))
        self.op_mode.blockSignals(False)
        for g, box in self.op_w.items():
            box.blockSignals(True)
            box.setValue(float((p.get('weights') or {}).get(g, 0.0)))
            box.blockSignals(False)
        for key, val in (('density', p['density']), ('gap', p['gap']), ('time', p['time_limit']), ('max_x', p['max_dims'][0]), ('max_y', p['max_dims'][1]), ('max_z', p['max_dims'][2])):
            self.op_f[key].blockSignals(True)
            self.op_f[key].setValue(float(val))
            self.op_f[key].blockSignals(False)
        for key, box in self.op_c.items():
            box.blockSignals(True)
            box.setCurrentIndex(max(0, box.findData(p[key])))
            box.blockSignals(False)
        for s, box in self.op_walls.items():
            box.blockSignals(True)
            box.setChecked(s in (p.get('locked_walls') or []))
            box.blockSignals(False)
        self.op_forbid.setText('; '.join(' '.join(f'{c:g}' for c in (*lo, *hi)) for lo, hi in p.get('forbidden') or []))
        self.encopt_target(recipe['target'], recipe.get('table'))

    def apply_encopt(self):
        if self.busy or self.mode != 'encopt' or not self.op_apply.isEnabled():
            return
        res = self.op.get('result')
        v = res['variants'][self.op['sel']]
        if not v['exact']['valid']:
            self.toast('Ten wariant narusza ograniczenia - nie można go zastosować.')
            return
        editing = (getattr(self, '_step_edit', None) or {}).get('recipe') or {}
        same = editing.get('type') == 'enc_opt'
        from .enclosure_param import group
        tb = self.document.get(self.op['target'])
        spec = enc.EnclosureSpec.from_json(tb.meta['enclosure'])
        recipe = dict(type='enc_opt', target=self.op['target'], mode=res['params']['mode'], params=res['params'], table=res['table'],
                      transforms=v['transforms'], axes=v['axes'] if res['params']['mode'] == 'A' else None,
                      summary=dict(dims=v['metrics']['dims'], change=v['change'], moved=v['moved'], rotated=v['rotated']),
                      reads=sorted({tb.id, *(g.id for g in group(self.document.bodies, tb)), *(s.id for s in spec.sources),
                                    *(b.id for b in self.document.bodies if (b.meta or {}).get('enclosure_mount_of') == tb.id)}))
        recipe['id'] = editing.get('id') if same and editing.get('id') else uuid.uuid4().hex
        existing = list(self.document.bodies)

        def build_step():
            return run(existing, recipe)

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Optymalizacja obudowy'
            self.document.pending_icon = 'encopt'
            self.document.commit(bodies)

        def after():
            self.view.set_preview_mesh(None)
            self.op.update(result=None, sel=None)
            self.op_list.clear()
            self.op_apply.setEnabled(False)

        self.view.set_preview_mesh(None)
        self.run_operation('Optymalizacja obudowy', build_step, apply, after=after)
