"""Generator obudów - etap 17 (okno): „Mocowania zewnętrzne” (Obudowy → Mocowania zewnętrzne).

Kliknięcie zewnętrznej płaskiej powierzchni części obudowy, rodzaj mocowania, rozmieszczenie (pojedyncze, symetryczne,
narożne, szyki, ręczne, według wskazanych punktów - kliknięcia na powierzchni), parametry i sposób wykonania (integralne,
osobna bryła, odłączane z otworami w obudowie). Wybrane mocowanie z listy można przesuwać strzałkami (u, v) i obracać
pierścieniem - rozmieszczenie przechodzi wtedy na ręczne. Podgląd uproszczony od razu, dokładny w tle. Zastosuj / Enter -
krok historii 'enc_ext' (parametry zapisane, edycja kroku, cofanie, regeneracja). Geometria: rccad.enclosure_external."""
from __future__ import annotations

import uuid

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QGridLayout, QListWidget, QListWidgetItem, QSpinBox

from . import enclosure_external as ex
from . import kernel
from . import shell_ui as ui
from .enclosure_ui import _label, _spin
from .enclosure_hole_ui import enclosure_bodies
from .enclosure_rib_ui import _context

EXT_LINE = (.2, .5, .9, 1)
EXT_HANDLE = (.2, .5, .9, 1)


def build(bodies, recipe):
    part, spec, env, lay, comps, others = _context(bodies, recipe['target'])
    sk = None
    sid = (recipe.get('params') or {}).get('sketch')
    if sid:
        sb = {b.id: b for b in bodies}.get(sid)
        if sb is None or sb.kind != 'sketch' or not sb.shape.Faces():
            raise kernel.CadError('Szkicu z obrysem mocowania już nie ma (albo nie jest zamknięty).')
        sk = sb.shape.Faces()[0].wrapped
    return ex.build(part.shape, recipe['face'], recipe['params'], comps, others, sk)


def run(bodies, recipe):
    """Krok 'enc_ext': mocowania zewnętrzne - część obudowy zmieniona (integralne / otwory), osobne bryły dodane
    (identyfikatory z przepisu - te same po edycji i regeneracji)."""
    from dataclasses import replace
    from .document import Body
    res = build(bodies, recipe)
    ids = list(recipe.get('out_ids') or [])
    while len(ids) < len(res['separate']):
        ids.append(uuid.uuid4().hex)
    old = set(recipe.get('out_ids') or [])
    recipe['out_ids'] = ids[:len(res['separate'])]
    out = []
    part = None
    for b in bodies:
        if b.id in old:
            continue                                        # poprzednie osobne mocowania tego kroku - zastąpione
        if b.id == recipe['target']:
            meta = dict(b.meta or {})
            meta['enclosure_ext'] = [*[r for r in meta.get('enclosure_ext', []) if r.get('id') != recipe.get('id')],
                                     {k: recipe[k] for k in recipe if k != 'type'}]
            b = replace(b, shape=res['part'], meta=meta, mesh=None).prepared()
            part = b
        out.append(b)
    label = ex.KIND_LABELS[recipe['params'].get('kind', 'wall')]
    for n, shape in enumerate(res['separate']):
        out.append(Body(f'{label} {n + 1}', shape, id=ids[n], folder=part.folder if part is not None else '',
                        meta=dict(enclosure_mount_of=recipe['target'], enclosure_mount_step=recipe.get('id'))).prepared())
    return out


class EnclosureExternalTools:
    def _build_encext_panel(self):
        self.ex = dict(target=None, face=None, positions=[], sel=None)
        self._ex_timer = QTimer(self)
        self._ex_timer.setSingleShot(True)
        self._ex_timer.setInterval(400)
        self._ex_timer.timeout.connect(lambda: self._ex_exact())
        self.ex_panel_w, lay = self._panel(312, 'Mocowania zewnętrzne', 'x_encext', 'Powierzchnia → rodzaj → rozmieszczenie', plain=True, scroll=True)
        self.ex_step1 = ui.StepRow(1, 'x_enclosure', 'Zewnętrzna powierzchnia', plain=True)
        lay.addWidget(self.ex_step1)
        self.ex_step2 = ui.StepRow(2, 'x_encext', 'Rodzaj i wykonanie', plain=True)
        lay.addWidget(self.ex_step2)
        self.ex_kind = QComboBox()
        for key in ex.KINDS:
            self.ex_kind.addItem(ex.KIND_LABELS[key], key)
        self.ex_kind.currentIndexChanged.connect(lambda *_: self._ex_update())
        lay.addWidget(self.ex_kind)
        self.ex_output = QComboBox()
        for key in ex.OUTPUTS:
            self.ex_output.addItem(ex.OUTPUT_LABELS[key], key)
        self.ex_output.currentIndexChanged.connect(lambda *_: self._ex_update())
        lay.addWidget(self.ex_output)
        self.ex_std = QComboBox()                           # szablony standardowe: szyna DIN / VESA / wkręt
        self.ex_std.currentIndexChanged.connect(lambda *_: self._ex_update())
        lay.addWidget(self.ex_std)
        self.ex_step3 = ui.StepRow(3, 'x_encext', 'Rozmieszczenie', plain=True)
        lay.addWidget(self.ex_step3)
        self.ex_layout = QComboBox()
        for key in ex.LAYOUTS:
            self.ex_layout.addItem(ex.LAYOUT_LABELS[key], key)
        self.ex_layout.currentIndexChanged.connect(lambda *_: self._ex_update())
        lay.addWidget(self.ex_layout)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        d = ex.DEFAULTS
        rows = (('width', 'Szerokość', .5), ('length', 'Długość', 0.0), ('height', 'Wysokość (VESA, słupki)', .5), ('thickness', 'Grubość materiału', .3),
                ('hole', 'Średnica otworów', .5), ('hole_pitch', 'Rozstaw otworów (0 = auto)', 0.0), ('slot_len', 'Długość otworów podłużnych', .5),
                ('radius', 'Promień narożników', 0.0), ('edge', 'Odległość od krawędzi', 0.0), ('angle', 'Kąt obrotu', -360.0),
                ('rib', 'Grubość żeber wzmacniających (0 = brak)', 0.0), ('clearance', 'Luz montażowy', 0.0), ('counterbore', 'Głębokość pogłębienia pod łeb', 0.0),
                ('head', 'Średnica łba śruby', .5), ('pitch', 'Rozstaw mocowań', .5), ('pitch2', 'Rozstaw rzędów', .5),
                ('du', 'Przesunięcie - w prawo', -1e4), ('dv', 'Przesunięcie - w górę', -1e4), ('blind', 'Głębokość otworów ślepych', .5),
                ('pipe', 'Średnica rury / profilu', 1.0), ('belt', 'Grubość paska', .5), ('belt_w', 'Szerokość paska', 1.0),
                ('tie_w', 'Szerokość opaski', .5), ('tie_h', 'Grubość opaski', .3), ('foot_d', 'Średnica nóżki / gniazda / słupka', 1.0),
                ('foot_h', 'Wysokość nóżki / głębokość gniazda', .3), ('tool_len', 'Miejsce na narzędzie', 0.0))
        self.ex_f = {}
        for n, (key, title, low) in enumerate(rows):
            box = _spin(d[key], low, 1e4, 2, 1 if key == 'angle' else .5, ' °' if key == 'angle' else ' mm')
            box.valueChanged.connect(lambda *_: self._ex_update())
            label = _label(title, 'label')
            grid.addWidget(label, n, 0)
            grid.addWidget(box, n, 1)
            self.ex_f[key] = (label, box)
        for m, (key, title) in enumerate((('count', 'Liczba mocowań'), ('rows', 'Rzędy'), ('cols', 'Kolumny'))):
            box = QSpinBox()
            box.setRange(1, 50)
            box.setValue(int(d[key]))
            box.setButtonSymbols(QSpinBox.NoButtons)
            box.setKeyboardTracking(False)
            box.valueChanged.connect(lambda *_: self._ex_update())
            label = _label(title, 'label')
            grid.addWidget(label, len(rows) + m, 0)
            grid.addWidget(box, len(rows) + m, 1)
            self.ex_f[key] = (label, box)
        lay.addLayout(grid)
        lay.addWidget(_label('Mocowania (zaznacz - strzałki przesuwają, pierścień obraca):', 'label'))
        self.ex_list = QListWidget()
        self.ex_list.setObjectName('enclist')
        self.ex_list.setFixedHeight(96)
        self.ex_list.currentRowChanged.connect(lambda row: self._ex_select(row))
        lay.addWidget(self.ex_list)
        self.ex_info = _label('', 'value')
        lay.addWidget(self.ex_info)
        self.ex_status = _label('Kliknij zewnętrzną płaską powierzchnię obudowy.', 'status')
        lay.addWidget(self.ex_status)
        self.ex_apply, _ = self._buttons(self.ex_panel_w.footer, 'Zastosuj', 'Anuluj', self.apply_encext, lambda: self.set_mode(None))
        self._ex_std_fill()
        return self.ex_panel_w

    def _ex_std_fill(self):
        kind = self.ex_kind.currentData()
        self.ex_std.blockSignals(True)
        self.ex_std.clear()
        if kind == 'din':
            for key, r in ex.DIN_RAILS.items():
                self.ex_std.addItem(f'Szyna {key} ({r["width"]:g} × {r["depth"]:g}, prześwit {r["opening"]:g}, blacha {r["sheet"]:g} mm)', key)
        elif kind == 'vesa':
            for key, s in ex.VESA.items():
                self.ex_std.addItem(f'VESA MIS-D {s:g} × {s:g} mm', key)
        else:
            for key, (d, head, _p) in ex.SCREWS.items():
                self.ex_std.addItem(f'Wkręt {key} (otwór {d:g}, łeb {head:g} mm)', key)
            self.ex_std.setCurrentIndex(max(0, self.ex_std.findData('M4')))
        self.ex_std.blockSignals(False)
        self.ex['std_kind'] = kind

    def _encext_begin(self):
        self.ex = dict(target=None, face=None, positions=[], sel=None)
        self.ex_panel_w.show()
        if not enclosure_bodies(self.document.bodies):
            self.toast('W projekcie nie ma obudowy z Generatora obudów - najpierw Utwórz obudowę.')
        self.hint('Mocowania zewnętrzne: kliknij zewnętrzną płaską powierzchnię obudowy, wybierz rodzaj i rozmieszczenie.')
        self.view.setCursor(Qt.PointingHandCursor)
        self._ex_update()

    def encext_hover(self, x, y):
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

    def encext_click(self, x, y, shift=False):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or not (body.meta or {}).get('enclosure') or body.kind != 'solid':
            self.toast('Kliknij zewnętrzną powierzchnię części obudowy.')
            return
        if self.ex_layout.currentData() == 'points' and self.ex.get('target') == body.id and self.ex.get('face'):
            fr = ex.frame_of(self.ex['face'])                # wskazane punkty: kliknięcia na powierzchni
            uv = ex.eh._uv([hit[2]], fr)[0]
            self.ex['positions'].append([float(uv[0]), float(uv[1]), float(self.ex_f['angle'][1].value())])
            self._ex_update()
            return
        try:
            face, _n = self.view.face_at(body, hit)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        if face is None or not kernel.is_planar_face(face):
            self.toast('Mocowania zewnętrzne powstają na płaskiej powierzchni.')
            return
        n = np.asarray(face.normalAt(face.Center()).toTuple(), float)
        self.ex.update(target=body.id, face=dict(point=[float(c) for c in face.Center().toTuple()], normal=[float(c) for c in n]), positions=[], sel=None)
        self._ex_update()

    def ex_params(self):
        out = {k: (int(b.value()) if k in ('count', 'rows', 'cols') else float(b.value())) for k, (_l, b) in self.ex_f.items()}
        kind = self.ex_kind.currentData()
        out.update(kind=kind, layout=self.ex_layout.currentData(), output=self.ex_output.currentData(), positions=[list(q) for q in self.ex['positions']],
                   sketch=self.ex.get('sketch'))
        std = self.ex_std.currentData()
        if kind == 'din':
            out['rail'] = std
        elif kind == 'vesa':
            out['vesa'] = std
        elif std:
            out['screw'] = std
        return out

    def ex_recipe(self):
        if not self.ex.get('target') or not self.ex.get('face'):
            return None
        return dict(type='enc_ext', target=self.ex['target'], face=dict(self.ex['face']), params=self.ex_params())

    def _ex_select(self, row):
        self.ex['sel'] = row if row >= 0 else None
        self._ex_handles()

    def _ex_handles(self):
        recipe = self.ex_recipe()
        sel = self.ex.get('sel')
        if recipe is None or sel is None or not self.ex.get('last_pos') or sel >= len(self.ex['last_pos']):
            self.view.set_handles([])
            return
        fr = ex.frame_of(recipe['face'])
        o, u, v, n = fr
        cu, cv, _a = self.ex['last_pos'][sel]
        c = o + u * cu + v * cv + n * float(recipe['params']['thickness'])
        self.view.set_handles([dict(id='ext:u', start=c, tip=c + u * 10, dir=u, color=EXT_HANDLE, label='Przesuń', min_px=36),
                               dict(id='ext:v', start=c, tip=c + v * 10, dir=v, color=EXT_HANDLE, label='Przesuń', min_px=36),
                               dict(id='ext:r', start=c, tip=c + n * 10, dir=n, color=(.94, .5, .1, 1), label='Obrót', min_px=36)])

    def encext_handle_dragged(self, hid, delta):
        """Przesuwanie / obracanie wybranego mocowania: rozmieszczenie przechodzi na ręczne (pozostałe mocowania zostają)."""
        sel = self.ex.get('sel')
        if sel is None or not self.ex.get('last_pos'):
            return
        drag = self.ex.get('drag')
        if drag is None or drag['id'] != hid:
            drag = self.ex['drag'] = dict(id=hid, start=[list(q) for q in self.ex['last_pos']])
        pos = [list(q) for q in drag['start']]
        if hid == 'ext:u':
            pos[sel][0] += float(delta)
        elif hid == 'ext:v':
            pos[sel][1] += float(delta)
        else:
            pos[sel][2] += float(delta) * 9.0               # 10 mm strzałki = 90°
        self.ex['positions'] = pos
        self.ex_layout.blockSignals(True)
        self.ex_layout.setCurrentIndex(self.ex_layout.findData('manual'))
        self.ex_layout.blockSignals(False)
        self._ex_update(exact=False)

    def encext_handle_released(self, hid):
        self.ex['drag'] = None
        self._ex_update()

    def _ex_update(self, exact=True):
        if not hasattr(self, 'ex_kind') or self.mode != 'encext':
            return
        kind = self.ex_kind.currentData()
        if self.ex.get('std_kind') != kind:
            self._ex_std_fill()
        lay = self.ex_layout.currentData()
        show = {'count': lay == 'linear', 'rows': lay == 'grid', 'cols': lay == 'grid', 'pitch': lay in ('linear', 'grid'), 'pitch2': lay == 'grid',
                'slot_len': kind in ('slot', 'keyhole'), 'pipe': kind == 'pipe', 'belt': kind == 'belt', 'belt_w': kind == 'belt',
                'tie_w': kind == 'tie', 'tie_h': kind == 'tie', 'foot_d': kind in ('feet', 'rubber', 'vesa'), 'foot_h': kind in ('feet', 'rubber'),
                'blind': kind == 'vesa', 'height': kind == 'vesa'}
        for key, (label, box) in self.ex_f.items():
            vis = show.get(key, True)
            label.setVisible(vis)
            box.setVisible(vis)
        tb = self.document.get(self.ex.get('target') or '')
        self.ex_step1.set_state('done' if tb else 'active', tb.name if tb else 'kliknij powierzchnię')
        self.ex_step2.set_state('done' if tb else 'pending', ex.KIND_LABELS[kind].lower())
        self.ex_step3.set_state('active' if tb else 'pending', ex.LAYOUT_LABELS[lay].lower())
        self.ex_apply.setEnabled(False)
        self._ex_timer.stop()
        recipe = self.ex_recipe()
        if recipe is None:
            self.view.set_preview_mesh(None)
            self.ex_info.setText('')
            return
        try:
            lo, hi, _f, fr = ex.face_bounds(tb.shape, recipe['face'])
            p = dict(ex.DEFAULTS, **recipe['params'])
            pos = ex.positions(p, lo, hi)
        except kernel.CadError as exc:
            self.view.set_preview_mesh(None)
            self.ex_status.setText(str(exc))
            return
        self.ex['last_pos'] = pos
        if self.ex_list.count() != len(pos):
            self.ex_list.blockSignals(True)
            self.ex_list.clear()
            for k in range(len(pos)):
                self.ex_list.addItem(QListWidgetItem(f'Mocowanie {k + 1}'))
            self.ex_list.blockSignals(False)
        self.view.set_preview_mesh(ex.preview_mesh(p, fr, lo, hi), color=(0, 0, 0, 0), line_color=EXT_LINE, width=1.6)
        self._ex_handles()
        self.ex_info.setText(f'Mocowania: {len(pos)}')
        self.ex_status.setText('Uproszczony podgląd - dokładna geometria za chwilę…')
        self._ex_sig = repr(recipe)
        if exact:
            self._ex_timer.start()

    def _ex_exact(self):
        recipe = self.ex_recipe()
        if recipe is None or self.mode != 'encext':
            return
        sig = repr(recipe)
        bodies = list(self.document.bodies)

        def compute():
            res = build(bodies, recipe)
            from .enclosure import merge_meshes
            meshes = [kernel.display_mesh(res['part'])] + [kernel.display_mesh(s) for s in res['separate']]
            return dict(mesh=merge_meshes(meshes), report=res['report'], separate=len(res['separate']))

        def show(value, error):
            if self.mode != 'encext' or getattr(self, '_ex_sig', None) != sig:
                return
            if error or value is None:
                self.ex_status.setText(str(error) if error else 'Nie udało się policzyć mocowań.')
                self.ex_apply.setEnabled(False)
                return
            self.view.set_preview_mesh(value['mesh'], color=(.55, .75, .95, .35), line_color=EXT_LINE, width=1.2)
            self.ex_info.setText('\n'.join(t for _l, t in value['report']) + (f'\nOsobne bryły: {value["separate"]}' if value['separate'] else ''))
            self.ex_status.setText('Enter albo Zastosuj dodaje mocowania.')
            self.ex_apply.setEnabled(True)
        self.run_preview('encext', compute, show)

    def _step_fill_enc_ext(self, recipe):
        p = dict(ex.DEFAULTS, **recipe['params'])
        self.ex.update(target=recipe['target'], face=dict(recipe['face']), positions=[list(q) for q in p.get('positions') or []], sel=None,
                       out_ids=list(recipe.get('out_ids') or []))
        combos = ((self.ex_kind, p['kind']), (self.ex_layout, p['layout']), (self.ex_output, p['output']))
        for box, val in combos:
            box.blockSignals(True)
            box.setCurrentIndex(max(0, box.findData(val)))
            box.blockSignals(False)
        self._ex_std_fill()
        std = p.get('rail') if p['kind'] == 'din' else p.get('vesa') if p['kind'] == 'vesa' else p.get('screw')
        self.ex_std.setCurrentIndex(max(0, self.ex_std.findData(std)))
        for k, (_l, box) in self.ex_f.items():
            if p.get(k) is not None:
                box.blockSignals(True)
                box.setValue(int(p[k]) if k in ('count', 'rows', 'cols') else float(p[k]))
                box.blockSignals(False)
        self._ex_update()

    def apply_encext(self):
        if self.busy or self.mode != 'encext' or not self.ex_apply.isEnabled():
            return
        recipe = self.ex_recipe()
        editing = (getattr(self, '_step_edit', None) or {}).get('recipe') or {}
        same = editing.get('type') == recipe['type']
        recipe['id'] = editing.get('id') if same and editing.get('id') else uuid.uuid4().hex
        recipe['seq'] = editing.get('seq') if same and 'seq' in editing else len(self.document.states())
        recipe['out_ids'] = list(editing.get('out_ids') or []) if same else []
        existing = list(self.document.bodies)

        def build_step():
            return run(existing, recipe)

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Mocowania zewnętrzne'
            self.document.pending_icon = 'encext'
            self.document.commit(bodies)

        def after():
            self.view.set_preview_mesh(None)
            self._ex_update()

        self._ex_timer.stop()
        self.view.set_preview_mesh(None)
        self.run_operation('Mocowania zewnętrzne', build_step, apply, after=after)
