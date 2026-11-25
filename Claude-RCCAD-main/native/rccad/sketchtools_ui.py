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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton

from . import dims
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
        self.sd_step1 = ui.StepRow(1, 'x_sdim', 'Pierwszy punkt', plain=True)
        self.sd_step2 = ui.StepRow(2, 'x_sdim', 'Drugi punkt', plain=True)
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
        self.sd_sym = QCheckBox('Rozsuń oba po równo')
        self.sd_sym.setToolTip('Wpisany wymiar rozsuwa (albo zsuwa) oba kształty po połowie - środek między punktami zostaje. '
                               'Bez zaznaczenia przesuwa się tylko kształt drugiego punktu.')
        self.sd_sym.toggled.connect(lambda *_: self._sd_preview())
        lay.addWidget(self.sd_sym)
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
            self.selected = []
            self.view.set_handles([])            # Wymiar: bez uchwytów zmiany rozmiaru kształtów
            self._sd_update()

    def _skt_body_ok(self, body):
        return (body is not None and body.kind == 'sketch' and body.visible and body.id not in self._eye_hidden() and not (body.meta or {}).get('surface')
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
        out = []
        for body in self.document.bodies:
            if not self._skt_body_ok(body):
                continue
            out.extend((body.id, p, kind, i) for i, (p, kind) in enumerate(dims.points_of(body.shape)))
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
        bid, p, kind, index = cands[j]
        return bid, np.asarray(p, float), kind, index

    KIND_NAMES = {'center': 'środek', 'end': 'koniec', 'mid': 'środek odcinka', 'free': 'punkt'}

    def _sd_free_point(self, x, y):
        """Punkt poza kształtami: przyciąga się jak przy rysowaniu linii (narożnik kratki siatki, krawędź, punkt szkicu; od
        pierwszego punktu poziomo / pionowo / pod 45°). (None, punkt 3D, 'free', -1, etykieta) albo None."""
        uv = self.view.plane_point(self.sketch_plane, x, y)
        if uv is None:
            return None
        saved = self.points
        a = self.sd.get('a') if self.sd.get('b') is None else None
        self.points = [tuple(kernel.uv_of(self.sketch_plane, tuple(float(c) for c in a[1]))[:2])] if a is not None else []
        try:
            u, v, label = self._snapper(x, y, uv)
        finally:
            self.points = saved
        p = np.asarray(kernel.to_world(self.sketch_plane, float(u), float(v)), float)
        return None, p, 'free', -1, label

    def _sd_hover(self, x, y):
        hit = self._sd_point_at(x, y)
        point = None
        if hit is not None:
            self.view.set_hover_body(hit[0] if self.sd['a'] is not None else None)
            self.view.set_marker(hit[1], label=self.KIND_NAMES.get(hit[2], 'punkt'))
            point = hit[1]
        else:
            free = self._sd_free_point(x, y)           # jak przy rysowaniu linii: siatka, krawędzie, poziom / pion / 45°
            self.view.set_hover_body(None)
            if free is not None:
                point = free[1]
                self.view.set_marker(point, label=free[4] or 'punkt')
            else:
                self.view.set_marker(None)
        a = self.sd.get('a')
        if a is not None and self.sd.get('b') is None:          # linia od pierwszego punktu do kursora (jak rysowana linia)
            mesh = None
            if point is not None and np.linalg.norm(point - a[1]) > 1e-9:
                mesh = kernel.display_mesh(dims.line_shape(a[1], point))
            aligned = getattr(self, '_line_aligned', None)
            self.view.set_preview_mesh(mesh, line_color=(.92, .12, .12, 1) if aligned else PREVIEW, width=2.4, dashed=not aligned)

    def _sd_click(self, x, y):
        hit = self._sd_point_at(x, y)
        if hit is None:
            body, edge = self._skt_body_at(x, y)
            if body is not None and self.sd['a'] is None and len(body.shape.Edges()) == 1 \
                    and body.shape.Edges()[0].geomType() == 'LINE':
                self._sd_shape_dims(body, edge)          # pojedyncza linia: wymiar jej długości
                return
            free = self._sd_free_point(x, y)
            if free is None:
                self.toast('Kliknij punkt szkicu albo miejsce na siatce.')
                return
            hit = free[:4]                               # stały punkt (siatka / krawędź): przesuwa się kształt drugiego końca
        if self.sd['a'] is None or self.sd['b'] is not None:
            self.override = {}
            self.sd = dict(a=hit, b=None)
        else:
            if float(np.linalg.norm(hit[1] - self.sd['a'][1])) < 1e-9:
                self.toast('Drugi punkt musi być w innym miejscu niż pierwszy.')
                return
            self.sd['b'] = hit
            self._sd_value_now()
        self._sd_update()

    def _sd_value_now(self):
        self.sd_value.blockSignals(True)
        self.sd_value.setValue(round(self._sd_current(), 3))
        self.sd_value.blockSignals(False)
        self.sd_value.setFocus()
        self.sd_value.selectAll()

    def _sd_shape_dims(self, body, edge):
        """Kliknięta linia bez punktu: pojedyncza prosta linia - wymiar jej długości (od końców). Wymiar nie otwiera okna
        zmiany rozmiaru kształtu - w tym narzędziu klik wybiera punkty, a przeciąganie przesuwa kształty."""
        e = body.shape.Edges()[edge]
        if len(body.shape.Edges()) == 1 and e.geomType() == 'LINE':      # pojedyncza linia: długość od jej końców
            pts = dims.points_of(body.shape)
            ends = [i for i, (_, kind) in enumerate(pts) if kind == 'end'][:2]
            if len(ends) == 2:
                self.sd = dict(a=(body.id, pts[ends[0]][0], 'end', ends[0]), b=(body.id, pts[ends[1]][0], 'end', ends[1]))
                self.sd_kind.setCurrentIndex(0)
                self._sd_value_now()
                self._sd_update()
                return
        self.toast('Kliknij punkt kształtu (środek okręgu, koniec albo środek linii). Przeciągnij kształt, żeby go przesunąć.')

    # ------------------------------------------------------------------ Wymiar: przesuwanie kształtów myszą
    SD_DRAG_PX = 4.0

    def _sd_hook(self, kind, x, y):
        """Lewy przycisk w narzędziu Wymiar: klik wybiera punkt, przeciągnięcie kształtu przesuwa go w płaszczyźnie szkicu
        (linie wymiarów idą za nim, wartości zmieniają się na bieżąco). Widok się nie obraca, uchwyty zmiany rozmiaru są
        wyłączone - przesuwać widok można prawym przyciskiem albo kółkiem."""
        if kind == 'press':
            body, _ = self._skt_body_at(x, y)
            uv = self.view.plane_point(self.sketch_plane, x, y)
            self._sd_drag = dict(x=x, y=y, body=body, uv=uv, moved=False, shift=None)
            return True
        drag = self.__dict__.get('_sd_drag')
        if drag is None:
            return True
        if kind == 'move':
            if not drag['moved'] and np.hypot(x - drag['x'], y - drag['y']) < self.SD_DRAG_PX:
                return True
            body = drag['body']
            if body is None or drag['uv'] is None:
                return True
            uv = self.view.plane_point(self.sketch_plane, x, y)
            if uv is None:
                return True
            drag['moved'] = True
            shift = np.asarray(kernel.to_world(self.sketch_plane, *uv), float) - np.asarray(kernel.to_world(self.sketch_plane, *drag['uv']), float)
            shift = self._sd_drag_snap(body, shift)
            drag['shift'] = shift
            try:
                self.override = {body.id: dims.moved(body, shift, self._meta_shape)}
            except Exception:
                self.override = {}
            self.refresh()
            return True
        self._sd_drag = None                     # puszczenie
        self.view.set_marker(None)
        if not drag['moved']:
            self._sd_click(x, y)                 # zwykłe kliknięcie: wybór punktu
            return True
        body, shift = drag['body'], drag['shift']
        self.override = {}
        if body is None or shift is None or float(np.linalg.norm(shift)) < 1e-9:
            self.refresh()
            return True
        moved = dims.moved(body, shift, self._meta_shape)
        self._dim_commit([moved if b.id == body.id else b for b in self.document.bodies], 'Przesunięcie szkicu', select=[])
        return True

    def _sd_drag_snap(self, body, shift):
        """Przeciągany kształt klei się do środków, wierzchołków, linii i stycznych innych szkiców tej płaszczyzny."""
        from . import movesnap
        if QApplication.keyboardModifiers() & Qt.AltModifier:
            self.view.set_marker(None)
            return shift
        try:
            frame = kernel.frame_of(self.sketch_plane)
            u = np.asarray(frame.xdir, float)
            v = np.cross(np.asarray(frame.normal, float), u)
            others = [b.shape for b in self.document.bodies if b.id != body.id and self._skt_body_ok(b)]
            moving, static = movesnap.gather([body.shape]), movesnap.gather(others)
            ppm = max(self.view._cam_ppm(), 1e-6)
            hit = movesnap.snap(shift, moving, static, [u, v], 10.0 / ppm)
        except Exception:
            hit = None
        if hit is None:
            self.view.set_marker(None)
            return shift
        corr, point, label = hit
        self.view.set_marker(point, label=label)
        return shift + corr

    # ------------------------------------------------------------------ prawy przycisk: odznaczanie w narzędziach
    def tool_right_deselect(self, x, y):
        """Prawy klik na wybranym elemencie (szkic, ściana, linia, punkt) w Lustrze, Połącz, Wymiarze, Dopasowaniu
        i Wyrównaniu odznacza go. Zwraca True, gdy coś odznaczono (wtedy widok się nie przesuwa)."""
        if self.busy:
            return False
        if self.mode == 'sketch' and self.tool in SKETCH_TOOLS:
            body, edge = self._skt_body_at(x, y)
            if self.tool == 'smirror':
                line = self.smr['line']
                if body is not None and body.id in self.smr['ids']:
                    self.smr['ids'].remove(body.id)
                elif line is not None and body is not None and body.name == line[2]:
                    self.smr['line'] = None
                else:
                    return False
                self._smr_update()
                return True
            if self.tool == 'sjoin':
                if body is None or body.id not in self.sj_ids:
                    return False
                self.sj_ids.remove(body.id)
                self._sj_update()
                return True
            if self.tool == 'sdim':
                hit = self._sd_point_at(x, y)
                a, b = self.sd['a'], self.sd['b']
                same = lambda h, k: h is not None and k is not None and h[0] == k[0] and np.linalg.norm(h[1] - k[1]) < 1e-9
                if same(hit, b):
                    self.sd['b'] = None
                elif same(hit, a):
                    self.sd = dict(a=b, b=None) if b is not None else dict(a=None, b=None)
                else:
                    return False
                self.override = {}
                self._sd_update()
                return True
            return False
        if self.mode in ('sfit', 'salign'):
            return self.splace_right(x, y)
        return False

    def _sd_axis(self):
        kind = self.sd_kind.currentData()
        if kind == 'free':
            return None
        f = kernel.frame_of(self.sketch_plane)
        x = np.asarray(f.xdir, float)
        return x if kind == 'u' else np.cross(np.asarray(f.normal, float), x)

    def _sd_current(self):
        return dims.measure(self.sd['a'][1], self.sd['b'][1], self._sd_axis())

    def _sd_kind_changed(self):
        if self.sd['b'] is not None:
            self.sd_value.blockSignals(True)
            self.sd_value.setValue(round(self._sd_current(), 3))
            self.sd_value.blockSignals(False)
        self._sd_preview()

    def _sd_ends(self):
        if self.sd['a'] is None or self.sd['b'] is None:
            raise kernel.CadError('Kliknij dwa punkty szkicu.')
        ends = []
        for bid, p, _kind, index in (self.sd['a'], self.sd['b']):
            if bid is None:
                ends.append(dims.ref_free(p))
                continue
            body = self.document.get(bid)
            if body is None:
                raise kernel.CadError('Kształtu wybranego punktu już nie ma.')
            ends.append(dims.ref(body, p, index))
        return ends

    def _sd_result(self, value=None):
        """{id: nowy kształt} po ustawieniu wymiaru (przesuwa się kształt drugiego punktu albo - przy „rozsuń po równo” - oba)."""
        a_end, b_end = self._sd_ends()
        value = float(self.sd_value.value() if value is None else value)
        return dims.apply(self.document.bodies, a_end, b_end, value, self._sd_axis(), self.sd_sym.isChecked(), self._meta_shape)

    def _sd_update(self):
        a, b = self.sd['a'], self.sd['b']
        name = lambda hit: (f'{self.KIND_NAMES.get(hit[2], "punkt")} · {self.document.get(hit[0]).name}' if self.document.get(hit[0])
                            else 'stały punkt (siatka)')
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
            self.override = self._sd_result()
            a_end, b_end = self._sd_ends()
            bodies = [self.override.get(b.id, b) for b in self.document.bodies]
            a, b = dims.end_point(a_end, bodies), dims.end_point(b_end, bodies)
            self.view.set_preview_mesh(kernel.display_mesh(dims.line_shape(a, b)) if np.linalg.norm(b - a) > 1e-9 else None,
                                       line_color=PREVIEW, width=2, dashed=True)
        except Exception:
            self.override = {}
            self.view.set_preview_mesh(None)
        self.refresh()

    def apply_sketch_dim(self):
        if self.busy or self.mode != 'sketch':
            return
        try:
            a_end, b_end = self._sd_ends()
            if a_end['id'] is None and b_end['id'] is None:
                changed = {}                 # dwa stałe punkty: sama linia wymiaru (pomiar), nic się nie przesuwa
            else:
                changed = self._sd_result()
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        value = self.sd_value.value()
        axis, sym = self._sd_axis(), self.sd_sym.isChecked()
        self.override = {}
        self.view.set_preview_mesh(None)
        self.sd = dict(a=None, b=None)
        self._sd_update()
        bodies = [changed.get(b.id, b) for b in self.document.bodies]
        # odstęp zostaje na polu roboczym jako purpurowa linia konstrukcyjna z wartością (pozycja „Linie konstrukcyjne”)
        cline = dims.make(self.sketch_plane, a_end, b_end, axis, sym, bodies)
        self._dim_commit([*bodies, cline], 'Wymiar szkicu', select=[])
        self.toast(f'Wymiar {value:g} mm ustawiony.', 2500)

    def _dim_commit(self, bodies, label, select=None):
        def apply(result):
            self.document.pending_op = None
            self.document.pending_label = label
            self.document.commit(result)

        def after():
            if select is not None:
                self.selected = [i for i in select if self.document.get(i) is not None]
            self.refresh()
        self.run_operation(label, lambda: list(bodies), apply, after=after)

    # ------------------------------------------------------------------ linie wymiarowe na polu roboczym
    def dim_value_set(self, cid, value):
        """Nowa wartość istniejącego wymiaru (edycja po kliknięciu wartości albo przeciągnięcie prawym przyciskiem)."""
        cline = self.document.get(cid)
        if cline is None or cline.kind != 'cline' or self.busy:
            return False
        d = cline.meta['dim']
        try:
            changed = dims.apply(self.document.bodies, d['a'], d['b'], float(value), d.get('axis'), d.get('sym'), self._meta_shape)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return False
        bodies = [changed.get(b.id, b) for b in self.document.bodies]
        bodies = [dims.refreshed(b, bodies) if b.id == cid else b for b in bodies]
        self._dim_commit(bodies, 'Wymiar szkicu', select=[cid])
        return True

    def _dim_item_at(self, x, y, labels_only=False):
        for rect, cid in reversed(getattr(self.view, 'dim_rects', [])):
            if rect.adjusted(-3, -3, 3, 3).contains(x, y):
                return cid
        if labels_only:
            return None
        best = None
        for cid, p, q in getattr(self.view, 'dim_segments', []):
            d = q - p
            t = float(np.clip(((np.array([x, y]) - p) @ d) / max(float(d @ d), 1e-9), 0, 1))
            dist = float(np.linalg.norm(p + d * t - [x, y]))
            if dist < 9 and (best is None or dist < best[0]):
                best = (dist, cid)
        return best[1] if best else None

    def dim_label_press(self, x, y):
        """Lewy klik w wartość wymiaru: zaznacza linię wymiaru i otwiera pole do wpisania nowej wartości."""
        cid = self._dim_item_at(x, y, labels_only=True)
        if cid is None or self.busy or self.document.get(cid) is None:
            return False                         # wymiary tylko do odczytu (np. przestrzeń obudowy) nie otwierają edycji
        self.selected = [cid]
        self.refresh()
        self._dim_edit_open(cid)
        return True

    def _dim_edit_open(self, cid):
        from PySide6.QtWidgets import QLineEdit
        item = next((it for it in getattr(self.view, 'dim_items', []) if it['id'] == cid), None)
        rect = next((r for r, i in getattr(self.view, 'dim_rects', []) if i == cid), None)
        if item is None or rect is None:
            return
        edit = getattr(self, '_dim_editor', None)
        if edit is None:
            edit = self._dim_editor = QLineEdit(self.view)
            edit.setObjectName('dimedit')
            edit.setAlignment(Qt.AlignCenter)
            edit.setStyleSheet('QLineEdit#dimedit { border:2px solid %s; border-radius:6px; background:white; color:#3d1450;'
                               ' font-weight:700; padding:1px 4px; }' % dims.COLOR)
            edit.returnPressed.connect(self._dim_edit_done)
            edit.editingFinished.connect(lambda: QTimer.singleShot(0, self._dim_edit_cancel_if_unfocused))
        edit.cid = cid
        edit.setText(f'{item["value"]:.3f}'.rstrip('0').rstrip('.'))
        width = max(76, int(rect.width()) + 26)
        edit.setGeometry(int(rect.center().x() - width / 2), int(rect.center().y() - 14), width, 28)
        edit.show()
        edit.raise_()
        edit.setFocus()
        edit.selectAll()

    def _dim_edit_done(self):
        edit = self._dim_editor
        text = edit.text().replace(',', '.').replace('mm', '').strip()
        edit.hide()
        try:
            value = float(text)
        except ValueError:
            self.toast('Wpisz liczbę (mm).')
            return
        if value <= 0:
            self.toast('Wymiar musi być większy od zera.')
            return
        self.dim_value_set(edit.cid, value)

    def _dim_edit_cancel_if_unfocused(self):
        edit = getattr(self, '_dim_editor', None)
        if edit is not None and edit.isVisible() and not edit.hasFocus():
            edit.hide()

    def dim_right_drag(self, stage, x, y):
        """Prawy przycisk na zaznaczonej linii wymiaru: przeciąganie przesuwa kształty wzdłuż niej, wymiar zmienia się na
        żywo; puszczenie zapisuje odległość."""
        if stage == 'press':
            if self.tool_right_deselect(x, y):
                self._dim_drag = None
                return True                      # prawy klik odznaczył element narzędzia
            cid = self._dim_item_at(x, y)
            if cid is None or cid not in self.selected or self.busy:
                return False
            item = next((it for it in self.view.dim_items if it['id'] == cid), None)
            if item is None:
                return False
            a, b = item['a'], item['b']
            axis = item['axis']
            direction = (b - a) if axis is None else axis * (1.0 if float((b - a) @ axis) >= 0 else -1.0)
            length = float(np.linalg.norm(direction))
            if length < 1e-9:
                return False
            direction = direction / length
            pa, pb = self.view.project_one(b), self.view.project_one(b + direction)
            if pa is None or pb is None:
                return False
            screen = np.asarray(pb, float) - np.asarray(pa, float)
            px = float(np.linalg.norm(screen))
            if px < 1e-6:
                return False
            self._dim_drag = dict(id=cid, x0=x, y0=y, value0=item['value'], screen=screen / px, px=px, sym=item['sym'], value=item['value'])
            return True
        drag = getattr(self, '_dim_drag', None)
        if drag is None:
            return False
        moved_px = float(np.array([x - drag['x0'], y - drag['y0']]) @ drag['screen'])
        value = drag['value0'] + moved_px / drag['px'] * (2.0 if drag['sym'] else 1.0)
        value = max(.1, round(value, 1))
        if stage == 'move':
            if abs(value - drag['value']) > 1e-9:
                drag['value'] = value
                cline = self.document.get(drag['id'])
                d = cline.meta['dim']
                try:
                    self.override = dims.apply(self.document.bodies, d['a'], d['b'], value, d.get('axis'), d.get('sym'), self._meta_shape)
                except kernel.CadError:
                    self.override = {}
                self.refresh()
            return True
        self._dim_drag = None
        self.override = {}
        if abs(drag['value'] - drag['value0']) > 1e-9:
            self.dim_value_set(drag['id'], drag['value'])
        else:
            self.refresh()
        return True


def cq_line(a, b):
    import cadquery as cq
    return cq.Wire.assembleEdges([cq.Edge.makeLine(cq.Vector(*[float(c) for c in a]), cq.Vector(*[float(c) for c in b]))])
