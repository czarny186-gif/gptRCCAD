"""Generator obudów - etap 16 (okno): narzędzie „Żebra wzmacniające” (Obudowy → Żebra wzmacniające).

Kliknięcie powierzchni części obudowy (Shift - kolejne powierzchnie tej samej części, płaskie albo zakrzywione), rodzaj
żeber, parametry, podgląd uproszczony (prostokąty żeber - natychmiast, także przy przeciąganiu strzałek wysokości i
rozstawu) i dokładny (w tle, po chwili). Lista żeber z możliwością usunięcia wybranych. Zastosuj / Enter - krok historii
'enc_rib' (parametry zapisane, edycja kroku, cofanie). Geometria: rccad.enclosure_ribs."""
from __future__ import annotations

import uuid

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QGridLayout, QListWidget, QListWidgetItem, QPushButton, QSpinBox

from . import enclosure as enc
from . import enclosure_ribs as er
from . import kernel
from . import shell_ui as ui
from .enclosure_ui import _label, _spin
from .enclosure_hole_ui import enclosure_bodies

RIB_LINE = (.85, .4, .05, 1)
RIB_HANDLE = (.94, .5, .1, 1)


def _context(bodies, target_id):
    """Część obudowy, jej definicja (spec, przestrzeń, układ), komponenty i pozostałe części grupy."""
    from .enclosure_param import group
    by_id = {b.id: b for b in bodies}
    part = by_id.get(target_id)
    if part is None or part.kind != 'solid' or not (part.meta or {}).get('enclosure'):
        raise kernel.CadError('Części obudowy wskazanej dla żeber już nie ma.')
    spec = enc.EnclosureSpec.from_json(part.meta['enclosure'])
    env = spec.envelope
    lay = enc.layout(env, spec, bodies=bodies)
    comps = [by_id[s.id].shape.wrapped for s in spec.sources if s.id in by_id and by_id[s.id].kind == 'solid']
    others = [b.shape.wrapped for b in group(bodies, part) if b.id != part.id and b.kind == 'solid'
              and not str((b.meta or {}).get('enclosure_part') or '').startswith(('flat_', 'bends_'))]
    return part, spec, env, lay, comps, others


def _sketch_edges(bodies, recipe, fr):
    sk = recipe['params'].get('sketch')
    if not sk:
        return None
    body = {b.id: b for b in bodies}.get(sk)
    if body is None or body.kind != 'sketch':
        raise kernel.CadError('Szkicu z liniami żeber już nie ma.')
    import cadquery as cq
    out = []
    for e in body.shape.Edges():
        pts = [e.positionAt(t).toTuple() for t in np.linspace(0, 1, 2 if e.geomType() == 'LINE' else 9)]
        uv = er.eh._uv(pts, fr)
        out += [(uv[k], uv[k + 1]) for k in range(len(uv) - 1)]
    return out


def build(bodies, recipe):
    part, spec, env, lay, comps, others = _context(bodies, recipe['target'])
    fr = er.frame_of(recipe['faces'][0])
    return er.build(part.shape, spec, env, lay, recipe['faces'], recipe['params'], comps, others, _sketch_edges(bodies, recipe, fr))


def run(bodies, recipe):
    """Krok historii 'enc_rib': żebra połączone z częścią obudowy (parametry zapisane w meta części)."""
    from dataclasses import replace
    shape, _info, _ribs = build(bodies, recipe)
    out = []
    for b in bodies:
        if b.id == recipe['target']:
            meta = dict(b.meta or {})
            meta['enclosure_ribs'] = [*[r for r in meta.get('enclosure_ribs', []) if r.get('id') != recipe.get('id')],
                                      {k: recipe[k] for k in recipe if k != 'type'}]
            b = replace(b, shape=shape, meta=meta, mesh=None).prepared()
        out.append(b)
    return out


class EnclosureRibTools:
    def _build_encrib_panel(self):
        self.er = dict(target=None, faces=[])
        self._er_timer = QTimer(self)
        self._er_timer.setSingleShot(True)
        self._er_timer.setInterval(450)
        self._er_timer.timeout.connect(lambda: self._er_exact())
        self.er_panel, lay = self._panel(312, 'Żebra wzmacniające', 'x_encrib', 'Powierzchnie → rodzaj → parametry', plain=True, scroll=True)
        self.er_step1 = ui.StepRow(1, 'x_enclosure', 'Powierzchnie (Shift - kolejne)', plain=True)
        lay.addWidget(self.er_step1)
        self.er_step2 = ui.StepRow(2, 'x_encrib', 'Rodzaj żeber', plain=True)
        lay.addWidget(self.er_step2)
        self.er_pattern = QComboBox()
        for key in er.PATTERNS:
            self.er_pattern.addItem(er.PATTERN_LABELS[key], key)
        self.er_pattern.setCurrentIndex(self.er_pattern.findData('parallel'))
        self.er_pattern.currentIndexChanged.connect(lambda *_: self._er_update(reset=True))
        lay.addWidget(self.er_pattern)
        self.er_sketch = QPushButton('Wskaż szkic z liniami żeber')
        self.er_sketch.clicked.connect(lambda _=False: self.er.update(picking_sketch=True) or self.er_status.setText('Kliknij szkic.'))
        lay.addWidget(self.er_sketch)
        self.er_step3 = ui.StepRow(3, 'x_encrib', 'Parametry', plain=True)
        lay.addWidget(self.er_step3)
        self.er_hmode = QComboBox()
        for key in er.HEIGHTS:
            self.er_hmode.addItem(er.HEIGHT_LABELS[key], key)
        self.er_hmode.currentIndexChanged.connect(lambda *_: self._er_update())
        lay.addWidget(self.er_hmode)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        d = er.DEFAULTS
        rows = (('thickness', 'Grubość żebra', d['thickness'], .2, ' mm'), ('height', 'Wysokość', d['height'], .2, ' mm'),
                ('height2', 'Wysokość 2 (końce / początek)', d['height2'], .2, ' mm'), ('taper_len', 'Długość ścięcia końców', d['taper_len'], 0.0, ' mm'),
                ('length', 'Długość (0 = do granic)', d['length'], 0.0, ' mm'), ('pitch', 'Rozstaw', d['pitch'], .5, ' mm'),
                ('pitch2', 'Rozstaw 2 (siatka, 0 = jak 1)', d['pitch2'], 0.0, ' mm'), ('angle', 'Kąt obrotu', d['angle'], -360.0, ' °'),
                ('draft', 'Pochylenie boków', d['draft'], 0.0, ' °'), ('fillet', 'Zaokrąglenie podstawy', d['fillet'], 0.0, ' mm'),
                ('margin', 'Margines od krawędzi', d['margin'], 0.0, ' mm'), ('gap', 'Min. odstęp od komponentów', d['gap'], 0.0, ' mm'),
                ('min_len', 'Min. długość fragmentu', d['min_len'], 0.0, ' mm'), ('min_h', 'Min. wysokość pod przeszkodą', d['min_h'], 0.0, ' mm'),
                ('cu', 'Środek - w prawo', d['cu'], -1e4, ' mm'), ('cv', 'Środek - w górę', d['cv'], -1e4, ' mm'))
        self.er_f = {}
        for n, (key, title, val, low, suf) in enumerate(rows):
            box = _spin(val, low, 1e4, 2, 1 if key in ('angle',) else .1, suf)
            box.valueChanged.connect(lambda *_: self._er_update())
            label = _label(title, 'label')
            grid.addWidget(label, n, 0)
            grid.addWidget(box, n, 1)
            self.er_f[key] = (label, box)
        box = QSpinBox()
        box.setRange(0, 400)
        box.setButtonSymbols(QSpinBox.NoButtons)
        box.setKeyboardTracking(False)
        box.valueChanged.connect(lambda *_: self._er_update(reset=True))
        label = _label('Liczba żeber (0 = auto)', 'label')
        grid.addWidget(label, len(rows), 0)
        grid.addWidget(box, len(rows), 1)
        self.er_f['count'] = (label, box)
        lay.addLayout(grid)
        self.er_obst = QComboBox()
        self.er_obst.addItem('Przeszkody: obniżaj żebra pod wysokimi, skracaj przy niskich', 'auto')
        self.er_obst.addItem('Przeszkody: zawsze skracaj / dziel żebra', 'cut')
        self.er_obst.currentIndexChanged.connect(lambda *_: self._er_update())
        lay.addWidget(self.er_obst)
        lay.addWidget(_label('Żebra (odznacz, aby usunąć wybrane):', 'label'))
        self.er_list = QListWidget()
        self.er_list.setObjectName('enclist')
        self.er_list.setFixedHeight(110)
        self.er_list.itemChanged.connect(lambda *_: self._er_list_changed())
        lay.addWidget(self.er_list)
        self.er_info = _label('', 'value')
        self.er_info.setStyleSheet('font-weight:700; color:#17314a;')
        lay.addWidget(self.er_info)
        self.er_status = _label('Kliknij powierzchnię obudowy (wewnętrzną albo zewnętrzną).', 'status')
        lay.addWidget(self.er_status)
        lay.addWidget(_label('Żebra nie mają obliczonej wytrzymałości - jej wzrost wymaga analizy mechanicznej.', 'status'))
        self.er_apply, _ = self._buttons(self.er_panel.footer, 'Zastosuj', 'Anuluj', self.apply_encrib, lambda: self.set_mode(None))
        return self.er_panel

    def _encrib_begin(self):
        self.er = dict(target=None, faces=[], removed=set())
        self.er_panel.show()
        if not enclosure_bodies(self.document.bodies):
            self.toast('W projekcie nie ma obudowy z Generatora obudów - najpierw Utwórz obudowę.')
        self.hint('Żebra wzmacniające: kliknij powierzchnię obudowy (Shift - kolejne), wybierz rodzaj i parametry.')
        self.view.setCursor(Qt.PointingHandCursor)
        self._er_update(reset=True)

    def _encrib_end(self):
        if hasattr(self, '_er_timer'):
            self._er_timer.stop()
        self.view.set_handles([])

    # ------------------------------------------------------------------ wskazywanie
    def encrib_hover(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        mesh = None
        if body is not None and (body.meta or {}).get('enclosure'):
            try:
                face, _n = self.view.face_at(body, hit, curved=True)
                mesh = kernel.display_mesh(face) if face is not None else None
            except Exception:
                mesh = None
        self.view.set_hover_mesh(mesh)

    def encrib_click(self, x, y, shift=False):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if self.er.get('picking_sketch'):
            if body is None or body.kind != 'sketch':
                self.toast('Kliknij szkic z liniami żeber.')
                return
            self.er['sketch'] = body.id
            self.er['picking_sketch'] = False
            self._er_update(reset=True)
            return
        if body is None or not (body.meta or {}).get('enclosure') or body.kind != 'solid':
            self.toast('Kliknij powierzchnię części obudowy z Generatora obudów.')
            return
        try:
            face, _n = self.view.face_at(body, hit, curved=True)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        if face is None:
            return
        import cadquery as cq
        if face.geomType() == 'PLANE':
            point = np.asarray(face.Center().toTuple(), float)
            n = np.asarray(face.normalAt(face.Center()).toTuple(), float)
        else:                                               # powierzchnia zakrzywiona: punkt kliknięcia i normalna w nim
            point = np.asarray(hit[2], float)
            n = np.asarray(face.normalAt(cq.Vector(*point)).toTuple(), float)
        item = dict(point=[float(c) for c in point], normal=[float(c) for c in n])
        if shift and self.er.get('target') == body.id:
            self.er['faces'].append(item)
        else:
            self.er.update(target=body.id, faces=[item])
        self._er_update(reset=True)

    # ------------------------------------------------------------------ parametry, podgląd
    def er_params(self):
        out = {k: (int(b.value()) if k == 'count' else float(b.value())) for k, (_l, b) in self.er_f.items()}
        out.update(pattern=self.er_pattern.currentData(), hmode=self.er_hmode.currentData(), obstacles=self.er_obst.currentData(),
                   sketch=self.er.get('sketch'), removed=sorted(self.er.get('removed') or []))
        return out

    def er_recipe(self):
        if not self.er.get('target') or not self.er.get('faces'):
            return None
        return dict(type='enc_rib', target=self.er['target'], faces=list(self.er['faces']), params=self.er_params())

    def _er_list_changed(self):
        removed = set()
        for i in range(self.er_list.count()):
            it = self.er_list.item(i)
            if it.checkState() != Qt.Checked:
                removed.add(int(it.data(Qt.UserRole)))
        self.er['removed'] = removed
        self._er_update()

    def _er_update(self, reset=False):
        if not hasattr(self, 'er_pattern') or self.mode != 'encrib':
            return
        pat = self.er_pattern.currentData()
        hm = self.er_hmode.currentData()
        show = {'pitch': pat in ('parallel', 'cross', 'grid', 'tri', 'hex', 'corner'), 'pitch2': pat == 'grid',
                'count': pat in ('parallel', 'cross', 'radial', 'post'), 'height2': hm != 'constant', 'taper_len': hm == 'ends',
                'angle': pat not in ('corner', 'sketch'), 'cu': pat in ('single', 'parallel', 'cross', 'grid', 'tri', 'hex', 'radial'),
                'cv': pat in ('single', 'parallel', 'cross', 'grid', 'tri', 'hex', 'radial')}
        for key, (label, box) in self.er_f.items():
            vis = show.get(key, True)
            label.setVisible(vis)
            box.setVisible(vis)
        self.er_sketch.setVisible(pat == 'sketch')
        if reset:
            self.er['removed'] = set()
        tb = self.document.get(self.er.get('target') or '')
        nf = len(self.er.get('faces') or [])
        self.er_step1.set_state('done' if tb else 'active', f'{tb.name}: {nf} pow.' if tb else 'kliknij powierzchnię')
        self.er_step2.set_state('done' if tb else 'pending', er.PATTERN_LABELS[pat].lower())
        self.er_step3.set_state('active' if tb else 'pending', '')
        self.er_apply.setEnabled(False)
        self._er_timer.stop()
        recipe = self.er_recipe()
        if recipe is None:
            self.view.set_preview_mesh(None)
            self.view.set_handles([])
            self.er_info.setText('')
            return
        try:
            meshes, all_segs = [], []
            p = dict(er.DEFAULTS, **recipe['params'])
            for face in recipe['faces']:
                reg, fr, _f = er.region(tb.shape, face, p)
                segs, raw = er.layout(dict(p, removed=[]), reg, fr, tb.shape.wrapped, _sketch_edges(self.document.bodies, recipe, fr))
                all_segs.append((fr, raw))
                kept = [s for k, s in enumerate(raw) if k not in self.er['removed']]
                meshes.append(er.preview_mesh(kept, fr, float(p['height'])))
        except kernel.CadError as exc:
            self.view.set_preview_mesh(None)
            self.er_status.setText(str(exc))
            self.er_info.setText('')
            return
        if reset or self.er_list.count() != sum(len(r) for _f, r in all_segs):
            self.er_list.blockSignals(True)
            self.er_list.clear()
            k = 0
            for _fr, raw in all_segs:
                for _s in raw:
                    it = QListWidgetItem(f'Żebro {k + 1}')
                    it.setData(Qt.UserRole, k)
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Unchecked if k in self.er['removed'] else Qt.Checked)
                    self.er_list.addItem(it)
                    k += 1
            self.er_list.blockSignals(False)
        from .enclosure import merge_meshes
        mesh = merge_meshes([m for m in meshes if m is not None]) if any(m is not None for m in meshes) else None
        self.view.set_preview_mesh(mesh, color=(0, 0, 0, 0), line_color=RIB_LINE, width=1.6)       # uproszczony podgląd
        self._er_place_handles(all_segs[0][0], p)
        self.er_info.setText(f'Żebra (przed dopasowaniem): {sum(len(r) for _f, r in all_segs) - len(self.er["removed"])}')
        self.er_status.setText('Uproszczony podgląd - dokładna geometria za chwilę…')
        self._er_sig = repr(recipe)
        self._er_timer.start()

    def _er_place_handles(self, fr, p):
        o, u, v, n = fr
        h = float(p['height'])
        handles = [dict(id='rib:height', start=o + n * h, tip=o + n * (h + 8.0), dir=n, color=RIB_HANDLE, label='Wysokość', min_px=40)]
        if p['pattern'] in ('parallel', 'cross', 'grid', 'tri', 'hex'):
            ang = np.radians(float(p['angle']))
            d = -u * np.sin(ang) + v * np.cos(ang)
            s0 = o + d * float(p['pitch'])
            handles.append(dict(id='rib:pitch', start=s0, tip=s0 + d * 8.0, dir=d, color=RIB_HANDLE, label='Rozstaw', min_px=40))
        self.view.set_handles(handles)

    def encrib_handle_dragged(self, hid, delta):
        """Strzałki wysokości i rozstawu: pole liczbowe idzie za strzałką, podgląd uproszczony (bez OCC) do puszczenia."""
        drag = self.er.get('drag')
        key = 'height' if hid == 'rib:height' else 'pitch'
        if drag is None or drag['id'] != hid:
            drag = self.er['drag'] = dict(id=hid, start=self.er_f[key][1].value())
        box = self.er_f[key][1]
        box.blockSignals(True)
        box.setValue(max(.2, round(drag['start'] + float(delta), 2)))
        box.blockSignals(False)
        self._er_update()
        self._er_timer.stop()                               # dokładna geometria dopiero po puszczeniu

    def encrib_handle_released(self, hid):
        self.er['drag'] = None
        self._er_update()

    def _er_exact(self):
        recipe = self.er_recipe()
        if recipe is None or self.mode != 'encrib':
            return
        sig = repr(recipe)
        bodies = list(self.document.bodies)

        def compute():
            shape, info, _ribs = build(bodies, recipe)
            return dict(mesh=kernel.display_mesh(shape), info=info)

        def show(value, error):
            if self.mode != 'encrib' or getattr(self, '_er_sig', None) != sig:
                return                                    # nieaktualny wynik
            if error or value is None:
                self.er_status.setText(str(error) if error else 'Nie udało się policzyć żeber.')
                self.er_apply.setEnabled(False)
                return
            info = value['info']
            self.view.set_preview_mesh(value['mesh'], color=(.95, .7, .45, .35), line_color=RIB_LINE, width=1.2)
            self.er_info.setText(f'Żebra po dopasowaniu: {info["count"]} brył, {info["volume"]:.0f} mm³ materiału'
                                 + (f'\nUsunięte fragmenty (za krótkie / niepołączone): {info["dropped"]}' if info['dropped'] else ''))
            self.er_status.setText('Enter albo Zastosuj dodaje żebra (połączone z częścią obudowy).')
            self.er_apply.setEnabled(True)
        self.run_preview('encrib', compute, show)

    def _step_fill_enc_rib(self, recipe):
        """Edycja kroku żeber: powierzchnie, rodzaj i parametry z przepisu."""
        p = dict(er.DEFAULTS, **recipe['params'])
        self.er.update(target=recipe['target'], faces=list(recipe['faces']), sketch=p.get('sketch'), removed=set(p.get('removed') or []))
        widgets = [self.er_pattern, self.er_hmode, self.er_obst, *[b for _l, b in self.er_f.values()]]
        for w_ in widgets:
            w_.blockSignals(True)
        self.er_pattern.setCurrentIndex(self.er_pattern.findData(p['pattern']))
        self.er_hmode.setCurrentIndex(self.er_hmode.findData(p['hmode']))
        self.er_obst.setCurrentIndex(self.er_obst.findData(p['obstacles']))
        for k, (_l, box) in self.er_f.items():
            if p.get(k) is not None:
                box.setValue(int(p[k]) if k == 'count' else float(p[k]))
        for w_ in widgets:
            w_.blockSignals(False)
        self._er_update()

    def apply_encrib(self):
        if self.busy or self.mode != 'encrib' or not self.er_apply.isEnabled():
            return
        recipe = self.er_recipe()
        editing = (getattr(self, '_step_edit', None) or {}).get('recipe') or {}
        same = editing.get('type') == recipe['type']
        recipe['id'] = editing.get('id') if same and editing.get('id') else uuid.uuid4().hex
        recipe['seq'] = editing.get('seq') if same and 'seq' in editing else len(self.document.states())
        existing = list(self.document.bodies)

        def build_step():
            return run(existing, recipe)

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Żebra wzmacniające'
            self.document.pending_icon = 'encrib'
            self.document.commit(bodies)

        def after():
            self.view.set_preview_mesh(None)
            self._er_update()

        self._er_timer.stop()
        self.view.set_preview_mesh(None)
        self.run_operation('Żebra wzmacniające', build_step, apply, after=after)
