"""Narzędzia szkicu z górnego paska (zakładka Szkic): Lustro szkicu, Połącz szkice i Wymiar.

Mixin okna Studio. Każde narzędzie działa w otwartym szkicu (self.mode == 'sketch', self.tool == klucz narzędzia):
- 'smirror' - klikane kształty szkicu odbijają się względem prostej linii szkicu albo osi poziomej / pionowej szkicu
  (krok historii 'sketch_mirror'); połowa profilu razem z odbiciem staje się jednym zamkniętym szkicem;
- 'sjoin' - klikane (albo wcześniej zaznaczone) szkice z jednej płaszczyzny łączą się w jeden szkic: stykające się końce
  linii tworzą ciągły obrys, więc Ofset, zaokrąglenie narożników i wyciągnięcie działają na cały kształt (krok 'sketch_join');
- 'sdim' - wymiar: dwa kliknięte punkty (końce linii, środki okręgów i łuków, środki odcinków) i wpisana odległość -
  kształt drugiego punktu przesuwa się tak, żeby odstęp był równy wpisanemu (prosto, poziomo albo pionowo). Kliknięcie
  linii albo okręgu (bez punktu) otwiera wymiary tego kształtu (długość, średnica, szerokość / wysokość…).
Geometria: kernel.sketch_join, kernel.sketch_points, kernel.mirror_plane; zapis: history.run_sketch_join / run_sketch_mirror,
a przesunięcie wymiarem - istniejąca zmiana szkicu (zapis w kroku, który utworzył kształt) albo krok Przesuń."""
from __future__ import annotations

import uuid

import numpy as np
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton

from . import history as hist
from . import kernel
from . import sketchmeta as sm
from . import shell_ui as ui

SKETCH_TOOLS = ('smirror', 'sjoin', 'sdim')
POINT_PICK_PX = 14.0          # promień przyciągania kursora do punktu szkicu przy wymiarowaniu (piksele)
PREVIEW = (.95, .45, .05, 1)


def _spin(value, low, high, decimals=3, step=1.0):
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    box.setButtonSymbols(QDoubleSpinBox.NoButtons)
    return box


def _label(text, name='label'):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class SketchTools:
    # ------------------------------------------------------------------ budowa paneli
    def _build_sketch_tool_panels(self):
        # --- lustro szkicu ---
        self.smr = dict(ids=[], line=None, stage='shapes')
        self.smr_panel, lay = self._panel(286, 'Lustro szkicu', 'x_smirror', 'Kształty → linia lustra', plain=True)
        self.smr_step1 = ui.StepRow(1, 'x_area', 'Kształty do odbicia', plain=True)
        self.smr_step2 = ui.StepRow(2, 'x_smirror', 'Linia lustra', plain=True)
        lay.addWidget(self.smr_step1)
        lay.addWidget(self.smr_step2)
        self.smr_pick_line = QPushButton('Wskaż linię lustra')
        self.smr_pick_line.setToolTip('Następne kliknięcie prostej linii szkicu wyznaczy linię lustra')
        self.smr_pick_line.clicked.connect(lambda _=False: self._smr_set_stage('line'))
        lay.addWidget(self.smr_pick_line)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.smr_axis_h = QPushButton('Oś pozioma')
        self.smr_axis_v = QPushButton('Oś pionowa')
        self.smr_axis_h.setToolTip('Lustro względem poziomej osi szkicu (przez początek układu szkicu)')
        self.smr_axis_v.setToolTip('Lustro względem pionowej osi szkicu (przez początek układu szkicu)')
        self.smr_axis_h.clicked.connect(lambda _=False: self._smr_axis('u'))
        self.smr_axis_v.clicked.connect(lambda _=False: self._smr_axis('v'))
        row.addWidget(self.smr_axis_h)
        row.addWidget(self.smr_axis_v)
        lay.addLayout(row)
        self.smr_keep = QCheckBox('Zachowaj oryginał (odbicie jako kopia)')
        self.smr_keep.setChecked(True)
        self.smr_keep.toggled.connect(lambda *_: self._smr_preview())
        lay.addWidget(self.smr_keep)
        self.smr_status = _label('Klikaj kształty szkicu.', 'status')
        lay.addWidget(self.smr_status)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_sketch_mirror, lambda: self.choose_tool(None))

        # --- połącz szkice ---
        self.sj_ids = []
        self.sj_panel, lay = self._panel(286, 'Połącz szkice', 'x_sjoin', 'Osobne linie → jeden szkic', plain=True)
        self.sj_status = _label('Klikaj szkice do połączenia.', 'status')
        lay.addWidget(self.sj_status)
        all_button = QPushButton('Zaznacz wszystkie w tym szkicu')
        all_button.clicked.connect(lambda _=False: self._sj_select_all())
        lay.addWidget(all_button)
        self.sj_tol = _spin(.01, .0001, 5, 4, .01)
        self.sj_tol.setToolTip('Końce linii bliżej niż ta odległość łączą się we wspólny wierzchołek')
        self._field(lay, 'Tolerancja końców (mm)', self.sj_tol)
        lay.addWidget(_label('Ponowny klik odznacza. Po połączeniu Ofset, zaokrąglenie narożników i wyciągnięcie działają na cały kształt.', 'hint'))
        self._buttons(lay, 'Połącz', 'Zamknij', self.apply_sketch_join, lambda: self.choose_tool(None))

        # --- wymiar ---
        self.sd = dict(a=None, b=None)
        self.sd_panel, lay = self._panel(286, 'Wymiar', 'x_sdim', 'Odstęp między punktami szkicu', plain=True)
        self.sd_step1 = ui.StepRow(1, 'x_sdim', 'Pierwszy punkt (zostaje)', plain=True)
        self.sd_step2 = ui.StepRow(2, 'x_sdim', 'Drugi punkt (ruchomy)', plain=True)
        lay.addWidget(self.sd_step1)
        lay.addWidget(self.sd_step2)
        self.sd_kind = QComboBox()
        for text, data in (('Odległość (najkrótsza)', 'free'), ('Poziomo (oś pozioma szkicu)', 'u'), ('Pionowo (oś pionowa szkicu)', 'v')):
            self.sd_kind.addItem(text, data)
        self.sd_kind.currentIndexChanged.connect(lambda *_: self._sd_kind_changed())
        self._field(lay, 'Kierunek wymiaru', self.sd_kind)
        self.sd_value = _spin(10, 0, 1e6, 3, 1)
        self.sd_value.valueChanged.connect(lambda *_: self._sd_preview())
        self._field(lay, 'Wymiar (mm)', self.sd_value)
        self.sd_status = _label('Kliknij pierwszy punkt.', 'status')
        lay.addWidget(self.sd_status)
        lay.addWidget(_label('Klik w samą linię / okrąg: jego wymiary.', 'hint'))
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_sketch_dim, lambda: self.choose_tool(None))
        return (self.smr_panel, self.sj_panel, self.sd_panel)

    def sketch_tool_panels(self):
        return (self.smr_panel, self.sj_panel, self.sd_panel)

    # ------------------------------------------------------------------ wspólne
    def _skt_begin(self, name, previous=()):
        """Wywoływane przez choose_tool: pokazuje panel wybranego narzędzia, czyści stan pozostałych."""
        sketch = self.mode == 'sketch'
        self.smr_panel.setVisible(name == 'smirror' and sketch)
        self.sj_panel.setVisible(name == 'sjoin' and sketch)
        self.sd_panel.setVisible(name == 'sdim' and sketch)
        self.smr = dict(ids=[], line=None, stage='shapes')
        self.sj_ids = []
        self.sd = dict(a=None, b=None)
        for key in SKETCH_TOOLS:
            if key in getattr(self, 'tools', {}):
                self.tools[key].setChecked(name == key and self.mode in ('sketch', 'plane'))
        if not sketch or name not in SKETCH_TOOLS:
            return
        chosen = [i for i in previous if self._skt_body_ok(self.document.get(i))]
        if name == 'smirror':
            self.smr['ids'] = chosen
            self._smr_update()
        elif name == 'sjoin':
            self.sj_ids = chosen
            self._sj_update()
        else:
            self._sd_update()

    def _skt_body_ok(self, body):
        return (body is not None and body.kind == 'sketch' and body.visible and not (body.meta or {}).get('surface')
                and self._same_plane(body.plane, self.sketch_plane))

    def _skt_cursor(self):
        pos = self.view.mapFromGlobal(QCursor.pos())
        return pos.x(), pos.y()

    def _skt_body_at(self, x, y):
        hit = self.view.nearest_edge(x, y, kinds=('sketch',))
        body = self.document.get(hit[0]) if hit else None
        return (body, hit[1]) if self._skt_body_ok(body) else (None, None)

    def _skt_show(self, ids):
        self.selected = [i for i in ids if self.document.get(i) is not None]
        self.refresh()

    def _toggle_sketch_tool(self, key):
        """Przycisk narzędzia szkicu na górnym pasku: w otwartym szkicu włącza / wyłącza narzędzie; poza szkicem otwiera
        szkic zaznaczonego kształtu (zaznaczenie zostaje wybrane w narzędziu) albo wybór płaszczyzny."""
        if self.mode == 'sketch':
            self.choose_tool(None if self.tool == key else key)     # zaznaczone kształty od razu trafiają do narzędzia
            return
        previous = list(self.selected)
        sketch = next((b for b in (self.document.get(i) for i in previous)
                       if b is not None and b.kind == 'sketch' and not (b.meta or {}).get('surface')), None)
        self.set_mode('plane')
        self.tool = key
        self._skt_pending = previous
        if sketch is not None:
            self.enter_sketch(sketch.plane)
        else:
            self.hint({'smirror': 'Lustro szkicu', 'sjoin': 'Połącz szkice', 'sdim': 'Wymiar'}[key]
                      + ': wskaż płaszczyznę szkicu (albo najpierw zaznacz kształt szkicu).')

    def skt_hover(self, x=None, y=None):
        if x is None:
            x, y = self._skt_cursor()
        if self.tool == 'smirror':
            self._smr_hover(x, y)
        elif self.tool == 'sjoin':
            body, _ = self._skt_body_at(x, y)
            self.view.set_hover_body(body.id if body is not None else None)
        elif self.tool == 'sdim':
            self._sd_hover(x, y)

    def skt_click(self, x=None, y=None, shift=False):
        if x is None:
            x, y = self._skt_cursor()
        if self.tool == 'smirror':
            self._smr_click(x, y)
        elif self.tool == 'sjoin':
            self._sj_click(x, y)
        elif self.tool == 'sdim':
            self._sd_click(x, y)

    def skt_apply(self):
        return {'smirror': self.apply_sketch_mirror, 'sjoin': self.apply_sketch_join, 'sdim': self.apply_sketch_dim}[self.tool]()

    def skt_escape(self):
        """Esc: najpierw cofa wybór w narzędziu; gdy nic nie wybrano - False (dalej zwykłe Esc)."""
        if self.tool == 'smirror' and (self.smr['ids'] or self.smr['line']):
            self._skt_begin('smirror')
        elif self.tool == 'sjoin' and self.sj_ids:
            self._skt_begin('sjoin')
        elif self.tool == 'sdim' and (self.sd['a'] is not None):
            self.override = {}
            self._skt_begin('sdim')
        else:
            return False
        self.selected = []
        self.view.set_preview_mesh(None)
        self.refresh()
        return True

    # ------------------------------------------------------------------ lustro
    def _smr_set_stage(self, stage):
        self.smr['stage'] = stage
        self._smr_update()

    def _smr_hover(self, x, y):
        body, edge = self._skt_body_at(x, y)
        if self.smr['stage'] == 'line':
            ok = body is not None and body.shape.Edges()[edge].geomType() == 'LINE'
            self.view._set_hover_edge((body.id, edge) if ok else None)
        else:
            self.view.set_hover_body(body.id if body is not None else None)

    def _smr_click(self, x, y):
        body, edge = self._skt_body_at(x, y)
        if body is None:
            self.toast('Kliknij linię kształtu narysowanego w tym szkicu.')
            return
        if self.smr['stage'] == 'line':
            e = body.shape.Edges()[edge]
            if e.geomType() != 'LINE':
                self.toast('Linia lustra musi być prostą linią (nie łukiem ani okręgiem).')
                return
            a, b = np.array(e.startPoint().toTuple(), float), np.array(e.endPoint().toTuple(), float)
            self.smr['line'] = (a, b, body.name)
            self.smr['stage'] = 'shapes'
            self.view._set_hover_edge(None)
        else:
            ids = self.smr['ids']
            if body.id in ids:
                ids.remove(body.id)
            else:
                ids.append(body.id)
        self._smr_update()

    def _smr_axis(self, which):
        if self.sketch_plane is None:
            return
        f = kernel.frame_of(self.sketch_plane)
        origin = np.asarray(f.origin, float)
        d = np.asarray(f.xdir if which == 'u' else np.cross(np.asarray(f.normal, float), np.asarray(f.xdir, float)), float)
        self.smr['line'] = (origin, origin + d, 'oś pozioma' if which == 'u' else 'oś pionowa')
        self.smr['stage'] = 'shapes'
        self._smr_update()

    def _smr_plane(self):
        """(origin, normal) płaszczyzny lustra: zawiera linię lustra i jest prostopadła do płaszczyzny szkicu."""
        a, b, _ = self.smr['line']
        n_sketch = np.asarray(kernel.frame_of(self.sketch_plane).normal, float)
        d = b - a
        normal = np.cross(d, n_sketch)
        if np.linalg.norm(normal) < 1e-9:
            raise kernel.CadError('Linia lustra nie może być prostopadła do szkicu.')
        return a, normal / np.linalg.norm(normal)

    def _smr_recipe(self):
        origin, normal = self._smr_plane()
        keep = self.smr_keep.isChecked()
        return dict(type='sketch_mirror', ids=list(self.smr['ids']), origin=[float(c) for c in origin], normal=[float(c) for c in normal],
                    keep=keep, out=[uuid.uuid4().hex for _ in self.smr['ids']] if keep else [])

    def _smr_update(self):
        ids = [i for i in self.smr['ids'] if self.document.get(i) is not None]
        self.smr['ids'] = ids
        self.smr_step1.set_state('done' if ids else 'active', f'{len(ids)} kształt(y)' if ids else 'kliknij kształty')
        line = self.smr['line']
        self.smr_step2.set_state('done' if line else ('active' if self.smr['stage'] == 'line' else 'pending'),
                                 line[2] if line else ('kliknij prostą linię' if self.smr['stage'] == 'line' else ''))
        self.smr_pick_line.setText('Kliknij prostą linię szkicu…' if self.smr['stage'] == 'line' else 'Wskaż linię lustra')
        if self.smr['stage'] == 'line':
            self.smr_status.setText('Kliknij prostą linię lustra.')
        elif not ids:
            self.smr_status.setText('Klikaj kształty szkicu.')
        elif not line:
            self.smr_status.setText('Wskaż linię lustra albo oś.')
        else:
            self.smr_status.setText('Enter odbija kształty.')
        self._skt_show(ids)
        self._smr_preview()

    def _smr_preview(self):
        if not self.smr['ids'] or not self.smr['line'] or self.mode != 'sketch':
            self.view.set_preview_mesh(None)
            return
        try:
            origin, normal = self._smr_plane()
            shapes = [kernel.mirror_plane(self.document.get(i).shape, normal, origin) for i in self.smr['ids']]
            self.view.set_preview_mesh(kernel.display_mesh(kernel.compound(shapes)), line_color=PREVIEW, width=2.4, dashed=True)
        except Exception:
            self.view.set_preview_mesh(None)

    def apply_sketch_mirror(self):
        if self.busy or self.mode != 'sketch':
            return
        if not self.smr['ids']:
            self.toast('Kliknij kształty szkicu do odbicia.')
            return
        if not self.smr['line']:
            self.toast('Wskaż linię lustra albo wybierz oś szkicu.')
            return
        try:
            recipe = self._smr_recipe()
            existing = list(self.document.bodies)
            hist.run_sketch_mirror(existing, recipe)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        self._skt_commit('Lustro szkicu', recipe, existing, hist.run_sketch_mirror)

    # ------------------------------------------------------------------ połącz
    def _sj_click(self, x, y):
        body, _ = self._skt_body_at(x, y)
        if body is None:
            self.toast('Kliknij linię szkicu narysowanego w tej płaszczyźnie.')
            return
        if body.id in self.sj_ids:
            self.sj_ids.remove(body.id)
        else:
            self.sj_ids.append(body.id)
        self._sj_update()

    def _sj_select_all(self):
        self.sj_ids = [b.id for b in self.document.bodies if self._skt_body_ok(b) and not b.name.startswith('Punkt')]
        self._sj_update()

    def _sj_update(self):
        self.sj_ids = [i for i in self.sj_ids if self.document.get(i) is not None]
        n = len(self.sj_ids)
        self.sj_status.setText('Klikaj szkice do połączenia.' if n == 0 else
                               f'Wybrano: {n}' + (' · Enter łączy' if n > 1 else ' · wybierz jeszcze jeden'))
        self._skt_show(self.sj_ids)
        preview = None
        if n > 1:
            try:
                preview = kernel.display_mesh(kernel.sketch_join([self.document.get(i).shape for i in self.sj_ids], self.sj_tol.value()))
            except Exception:
                preview = None
        self.view.set_preview_mesh(preview, line_color=PREVIEW, width=3)

    def apply_sketch_join(self):
        if self.busy or self.mode != 'sketch':
            return
        if len(self.sj_ids) < 2:
            self.toast('Wybierz co najmniej dwa szkice do połączenia.')
            return
        recipe = dict(type='sketch_join', ids=list(self.sj_ids), tol=float(self.sj_tol.value()))
        existing = list(self.document.bodies)
        try:
            hist.run_sketch_join(existing, recipe)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        self._skt_commit('Połączenie szkiców', recipe, existing, hist.run_sketch_join, select=[recipe['ids'][0]])

    def _skt_commit(self, label, recipe, existing, runner, select=None):
        def build():
            return list(runner(existing, recipe))

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = label
            self.document.commit(bodies)

        def after():
            tool = self.tool
            self.view.set_preview_mesh(None)
            if self.mode == 'sketch' and tool in SKETCH_TOOLS:
                self._skt_begin(tool)
            self.selected = [i for i in (select or []) if self.document.get(i) is not None]
            self.refresh()
            self.toast(f'{label} - gotowe.', 2500)
        self.run_operation(label, build, apply, after=after)

    # ------------------------------------------------------------------ wymiar
    def _sd_candidates(self):
        cache = self.__dict__.setdefault('_sd_cache', {})
        out = []
        for body in self.document.bodies:
            if not self._skt_body_ok(body):
                continue
            hit = cache.get(body.id)
            if hit is None or hit[0] is not body.shape:
                try:
                    pts = kernel.sketch_points(body.shape)
                except Exception:
                    pts = []
                hit = cache[body.id] = (body.shape, pts)
            out.extend((body.id, p, kind) for p, kind in hit[1])
        return out

    def _sd_point_at(self, x, y, radius=POINT_PICK_PX):
        cands = self._sd_candidates()
        if not cands:
            return None
        xy, _, w = self.view.project_points(np.asarray([c[1] for c in cands], float))
        dist = np.linalg.norm(xy - [x, y], axis=1)
        dist[~np.isfinite(dist) | (w <= 0)] = np.inf
        # przy wspólnym punkcie dwóch kształtów pierwszeństwo ma środek (okrąg), potem koniec linii
        order = {'center': 0, 'end': 1, 'mid': 2}
        j = min(range(len(cands)), key=lambda i: (round(float(dist[i]) / 3.0), order.get(cands[i][2], 3)))
        if dist[j] > radius:
            return None
        bid, p, kind = cands[j]
        return bid, np.asarray(p, float), kind

    KIND_NAMES = {'center': 'środek', 'end': 'koniec', 'mid': 'środek odcinka'}

    def _sd_hover(self, x, y):
        hit = self._sd_point_at(x, y)
        if hit is not None:
            self.view.set_hover_body(hit[0] if self.sd['a'] is not None else None)
            self.view.set_marker(hit[1], label=self.KIND_NAMES.get(hit[2], 'punkt'))
            return
        self.view.set_marker(None)
        body, _ = self._skt_body_at(x, y)
        self.view.set_hover_body(body.id if body is not None and self.sd['a'] is None else None)

    def _sd_click(self, x, y):
        hit = self._sd_point_at(x, y)
        if hit is None:
            body, edge = self._skt_body_at(x, y)
            if body is None:
                self.toast('Kliknij punkt szkicu (koniec linii, środek okręgu) albo linię / okrąg.')
                return
            self._sd_shape_dims(body, edge)
            return
        if self.sd['a'] is None or self.sd['b'] is not None:
            self.override = {}
            self.sd = dict(a=hit, b=None)
        else:
            if float(np.linalg.norm(hit[1] - self.sd['a'][1])) < 1e-9:
                self.toast('Drugi punkt musi być w innym miejscu niż pierwszy.')
                return
            self.sd['b'] = hit
            self.sd_value.blockSignals(True)
            self.sd_value.setValue(round(self._sd_current(), 3))
            self.sd_value.blockSignals(False)
            self.sd_value.setFocus()
            self.sd_value.selectAll()
        self._sd_update()

    def _sd_shape_dims(self, body, edge):
        """Kliknięta linia / okrąg bez punktu: wymiary samego kształtu (istniejące okno wymiarów szkicu)."""
        if body.meta and body.meta.get('tool') in sm.EDITABLE:
            self.selected = [body.id]
            self._last_sketch_id = body.id
            self.open_dim_edit()
            return
        e = body.shape.Edges()[edge]
        if len(body.shape.Edges()) == 1 and e.geomType() == 'LINE':      # pojedyncza linia bez wymiarów: długość od jej końców
            a, b = np.array(e.startPoint().toTuple(), float), np.array(e.endPoint().toTuple(), float)
            self.sd = dict(a=(body.id, a, 'end'), b=(body.id, b, 'end'))
            self.sd_kind.setCurrentIndex(0)
            self.sd_value.blockSignals(True)
            self.sd_value.setValue(round(float(np.linalg.norm(b - a)), 3))
            self.sd_value.blockSignals(False)
            self.sd_value.setFocus()
            self.sd_value.selectAll()
            self._sd_update()
            return
        self.toast('Ten kształt nie ma własnych wymiarów - kliknij dwa jego punkty (np. środek okręgu i koniec linii).')

    def _sd_axis(self):
        kind = self.sd_kind.currentData()
        if kind == 'free':
            return None
        f = kernel.frame_of(self.sketch_plane)
        x = np.asarray(f.xdir, float)
        return x if kind == 'u' else np.cross(np.asarray(f.normal, float), x)

    def _sd_current(self):
        a, b = self.sd['a'][1], self.sd['b'][1]
        axis = self._sd_axis()
        return float(np.linalg.norm(b - a)) if axis is None else abs(float((b - a) @ axis))

    def _sd_kind_changed(self):
        if self.sd['b'] is not None:
            self.sd_value.blockSignals(True)
            self.sd_value.setValue(round(self._sd_current(), 3))
            self.sd_value.blockSignals(False)
        self._sd_preview()

    def _sd_shift(self, value=None):
        """Wektor przesunięcia kształtu drugiego punktu, po którym wymiar ma wartość value."""
        a, b = self.sd['a'][1], self.sd['b'][1]
        value = float(self.sd_value.value() if value is None else value)
        axis = self._sd_axis()
        if axis is None:
            d = b - a
            length = float(np.linalg.norm(d))
            if length < 1e-12:
                raise kernel.CadError('Punkty leżą w tym samym miejscu - nie wiadomo, w którą stronę przesunąć.')
            return d / length * (value - length)
        cur = float((b - a) @ axis)
        sign = 1.0 if cur >= 0 else -1.0
        return axis * (sign * value - cur)

    def _sd_result(self, value=None):
        """(stary kształt, nowy kształt, nowe meta) po ustawieniu wymiaru."""
        if self.sd['a'] is None or self.sd['b'] is None:
            raise kernel.CadError('Kliknij dwa punkty szkicu.')
        same = self.sd['a'][0] == self.sd['b'][0]
        body = self.document.get(self.sd['b'][0])
        if body is None:
            raise kernel.CadError('Kształtu drugiego punktu już nie ma.')
        shift = self._sd_shift(value)
        if same:
            return (body, *self._sd_same_body(body, shift))
        return (body, *self._sd_moved(body, shift))

    def _sd_moved(self, body, shift):
        meta = body.meta
        if meta and meta.get('tool') in sm.EDITABLE and meta.get('points'):
            p0 = np.asarray(kernel.uv_of(body.plane, (0.0, 0.0, 0.0)), float)
            p1 = np.asarray(kernel.uv_of(body.plane, tuple(float(c) for c in shift)), float)
            du, dv = (p1 - p0).tolist()
            meta2 = dict(meta, points=[[round(float(p[0]) + du, 6), round(float(p[1]) + dv, 6)] for p in meta['points']])
            return self._meta_shape(body.plane, meta2), meta2
        return body.shape.translate(tuple(float(c) for c in shift)), None

    def _sd_same_body(self, body, shift):
        """Oba punkty na jednym kształcie: linia (z wymiarami albo pojedyncza) zmienia długość - przesuwa się drugi koniec."""
        meta = body.meta
        b = self.sd['b'][1]
        if meta and meta.get('tool') == 'line' and len(meta.get('points') or ()) == 2:
            ends = [np.asarray(kernel.to_world(body.plane, *p), float) for p in meta['points']]
            k = int(np.argmin([np.linalg.norm(e - b) for e in ends]))
            if np.linalg.norm(ends[k] - b) < 1e-4:
                pts = [list(p) for p in meta['points']]
                uv = kernel.uv_of(body.plane, tuple(float(c) for c in b + shift))
                pts[k] = [round(float(uv[0]), 6), round(float(uv[1]), 6)]
                meta2 = dict(meta, points=pts)
                return self._meta_shape(body.plane, meta2), meta2
        edges = body.shape.Edges()
        if len(edges) == 1 and edges[0].geomType() == 'LINE':
            s, e = np.array(edges[0].startPoint().toTuple(), float), np.array(edges[0].endPoint().toTuple(), float)
            if np.linalg.norm(e - b) < np.linalg.norm(s - b):
                e = e + shift
            else:
                s = s + shift
            if np.linalg.norm(e - s) < 1e-6:
                raise kernel.CadError('Wymiar musi być większy od zera.')
            return cq_line(s, e), None
        raise kernel.CadError('Oba punkty leżą na tym samym kształcie - wybierz punkty dwóch różnych kształtów '
                              '(albo kliknij sam kształt, żeby zmienić jego wymiary).')

    def _sd_update(self):
        a, b = self.sd['a'], self.sd['b']
        name = lambda hit: f'{self.KIND_NAMES.get(hit[2], "punkt")} · {self.document.get(hit[0]).name}' if self.document.get(hit[0]) else ''
        self.sd_step1.set_state('done' if a else 'active', name(a) if a else 'kliknij punkt')
        self.sd_step2.set_state('done' if b else ('active' if a else 'pending'), name(b) if b else ('kliknij drugi punkt' if a else ''))
        if a is None:
            self.sd_status.setText('Kliknij pierwszy punkt.')
        elif b is None:
            self.sd_status.setText('Kliknij drugi punkt.')
        else:
            self.sd_status.setText(f'Teraz {self._sd_current():.3f} mm · wpisz wymiar, Enter')
        self._sd_preview()

    def _sd_preview(self):
        if self.sd.get('b') is None or self.mode != 'sketch':
            if self.override:
                self.override = {}
                self.refresh()
            self.view.set_preview_mesh(None)
            return
        try:
            body, shape, meta = self._sd_result()
            self.override = {body.id: replace(body, shape=shape, mesh=kernel.display_mesh(shape), meta=meta if meta is not None else body.meta)}
            a = self.sd['a'][1]
            b = self.sd['b'][1] + self._sd_shift()
            self.view.set_preview_mesh(kernel.display_mesh(cq_line(a, b)) if np.linalg.norm(b - a) > 1e-9 else None,
                                       line_color=PREVIEW, width=2, dashed=True)
        except Exception:
            self.override = {}
            self.view.set_preview_mesh(None)
        self.refresh()

    def apply_sketch_dim(self):
        if self.busy or self.mode != 'sketch':
            return
        try:
            body, shape, meta = self._sd_result()
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        value = self.sd_value.value()
        self.override = {}
        self.view.set_preview_mesh(None)
        self.sd = dict(a=None, b=None)
        self._sd_update()
        if meta is not None:
            self._commit_sketch_edit(body, shape, meta)          # wymiarowany kształt: zmiana zapisana razem z jego wymiarami
        else:
            self._sd_commit_plain(body, shape)
        self.toast(f'Wymiar {value:g} mm ustawiony.', 2500)

    def _sd_commit_plain(self, body, shape):
        """Kształt bez wymiarów (np. połączony albo z ofsetu): nowe położenie zapisane w kroku, który go utworzył, a gdy się
        nie da - zwykły krok Przesuń (przesunięcie) albo zmiana kształtu."""
        new = replace(body, shape=shape, mesh=kernel.display_mesh(shape), meta=None if not (body.meta or {}).get('surface') else body.meta)
        if not self.document.merging and self.amend_objects({body.id: new}, 'Wymiar szkicu', select=[body.id]):
            return
        c0 = np.array(body.shape.Center().toTuple(), float)
        c1 = np.array(shape.Center().toTuple(), float)
        moved = body.shape.translate(tuple(float(c) for c in c1 - c0))
        rigid = len(shape.Edges()) == len(body.shape.Edges()) and abs(moved.BoundingBox().DiagonalLength - shape.BoundingBox().DiagonalLength) < 1e-6
        existing = list(self.document.bodies)
        if rigid:
            recipe = dict(type='transform', mode='move', id=body.id, v=[float(c) for c in c1 - c0])
            build = lambda: list(hist.run_transform(existing, recipe))
        else:
            recipe = None
            build = lambda: [new if b.id == body.id else b for b in existing]

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Wymiar szkicu'
            self.document.commit(bodies)
        self.run_operation('Wymiar szkicu', build, apply)


def cq_line(a, b):
    import cadquery as cq
    return cq.Wire.assembleEdges([cq.Edge.makeLine(cq.Vector(*[float(c) for c in a]), cq.Vector(*[float(c) for c in b]))])
