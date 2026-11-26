"""Generator obudów - etap 19 (okno): „Panel sterowania” (Obudowy → Panel sterowania).

Kliknięcie zewnętrznej płaskiej powierzchni części obudowy, potem dodawanie elementów (rodzaj + parametry; położenie z
pola albo z kliknięcia komponentu - środek jego rzutu i odległość od ścianki, komponent bez zmian). Lista elementów
(wybór, usuwanie), rozmieszczanie (wyrównanie, centrowanie, symetria, równy rozstaw, szyk), strzałki przesuwające
wybrany element. Podgląd dokładny w tle. Zastosuj / Enter - krok 'enc_panel' (parametry zapisane, edycja, cofanie,
regeneracja; pokrętła, przyciski, prowadnice światła i okna to osobne bryły). Geometria: rccad.enclosure_panel."""
from __future__ import annotations

import uuid

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QListWidget, QPushButton

from . import enclosure_panel as pn
from . import kernel
from . import shell_ui as ui
from .enclosure_ui import _label, _spin
from .enclosure_hole_ui import enclosure_bodies
from .enclosure_rib_ui import _context

PANEL_LINE = (.55, .2, .75, 1)
FIELDS = {'display': ('active_w', 'active_h', 'module_w', 'module_h', 'module_t', 'module_du', 'module_dv', 'frame_l', 'frame_r', 'frame_t', 'frame_b', 'bezel', 'conn_w', 'conn_h'),
          'touch': ('active_w', 'active_h', 'module_w', 'module_h', 'module_t', 'frame_l', 'frame_r', 'frame_t', 'frame_b', 'bezel'),
          'recess': ('module_w', 'module_h', 'depth'), 'encoder': ('diameter',), 'pot': ('diameter',),
          'knob': ('diameter', 'height', 'shaft', 'flat', 'insert', 'sides', 'splines'), 'button': ('diameter', 'height', 'travel', 'stem', 'stop'),
          'membrane': ('width', 'height', 'depth', 'conn_w'), 'slider': ('width', 'length'), 'switch': ('width', 'height'),
          'lightpipe': ('pipe_d', 'pipe_d2', 'stem', 'bend'), 'speaker': ('diameter', 'hole', 'web'), 'mic': ('hole', 'diameter', 'gasket'),
          'window': ('width', 'height', 'window_t', 'bezel')}
TITLES = dict(active_w='Pow. aktywna - szerokość', active_h='Pow. aktywna - wysokość', module_w='Moduł - szerokość', module_h='Moduł - wysokość',
              module_t='Moduł - grubość', module_du='Moduł - przesunięcie w bok', module_dv='Moduł - przesunięcie w górę', frame_l='Ramka z lewej (+ odsłania)',
              frame_r='Ramka z prawej', frame_t='Ramka u góry', frame_b='Ramka u dołu', bezel='Ramka / obrzeże', conn_w='Złącze / taśma - szerokość',
              conn_h='Złącze - wysokość', depth='Głębokość wnęki', diameter='Średnica', height='Wysokość', shaft='Wałek - średnica', flat='Wałek D - wymiar ścięcia',
              insert='Głębokość osadzenia', sides='Liczba boków', splines='Liczba wypustów', travel='Skok roboczy', stem='Odległość od ścianki (0 = komponent)',
              stop='Ogranicznik (kołnierz)', width='Szerokość', length='Długość', pipe_d='Średnica prowadnicy', pipe_d2='Średnica stopnia',
              bend='Przesunięcie łuku', hole='Średnica otworów', web='Materiał między otworami', gasket='Wnęka uszczelki', window_t='Grubość okna',
              u='Położenie - w prawo', v='Położenie - w górę', angle='Obrót', clearance='Luz')
CHOICES = dict(mount=(('below', 'Montaż poniżej powierzchni'), ('flush', 'Na równi z powierzchnią'), ('above', 'Powyżej powierzchni (ramka)')),
               knob=tuple((k, {'cylinder': 'Pokrętło cylindryczne', 'cone': 'Stożkowe', 'polygon': 'Wielokątne', 'knurled': 'Radełkowane', 'handle': 'Z uchwytem'}[k]) for k in pn.KNOBS),
               bore=tuple((k, {'round': 'Wałek okrągły', 'd': 'Wałek typu D', 'hex': 'Sześciokątny', 'spline': 'Wielowypustowy', 'sketch': 'Profil ze szkicu'}[k]) for k in pn.BORES),
               pipe=tuple((k, {'straight': 'Prowadnica prosta', 'stepped': 'Stopniowana', 'curved': 'Zakrzywiona'}[k]) for k in pn.PIPES),
               shape=(('flat', 'Powierzchnia płaska'), ('dome', 'Wypukła'), ('square', 'Kwadratowa')),
               pattern=(('hex', 'Otwory sześciokątne'), ('circle', 'Okrągłe'), ('radial', 'Promieniowe'), ('slot', 'Szczeliny')))


def build(bodies, recipe):
    part, spec, env, lay, comps, others = _context(bodies, recipe['target'])
    items = []
    for it in recipe['items']:
        it = dict(it)
        if it.get('bore') == 'sketch' and it.get('bore_sketch'):
            sb = {b.id: b for b in bodies}.get(it['bore_sketch'])
            if sb is None or not sb.shape.Faces():
                raise kernel.CadError('Szkicu z profilem otworu na wałek już nie ma.')
            it['bore_face'] = sb.shape.Faces()[0].wrapped
        items.append(it)
    return pn.build(part.shape, recipe['face'], items, comps, others)


def run(bodies, recipe):
    from dataclasses import replace
    from .document import Body
    res = build(bodies, recipe)
    ids = list(recipe.get('out_ids') or [])
    while len(ids) < len(res['parts']):
        ids.append(uuid.uuid4().hex)
    old = set(recipe.get('out_ids') or [])
    recipe['out_ids'] = ids[:len(res['parts'])]
    out, part = [], None
    for b in bodies:
        if b.id in old:
            continue
        if b.id == recipe['target']:
            meta = dict(b.meta or {})
            meta['enclosure_panels'] = [*[r for r in meta.get('enclosure_panels', []) if r.get('id') != recipe.get('id')],
                                        {k: recipe[k] for k in recipe if k != 'type'}]
            b = replace(b, shape=res['part'], meta=meta, mesh=None).prepared()
            part = b
        out.append(b)
    for n, (name, shape) in enumerate(res['parts']):
        out.append(Body(f'{name} {n + 1}', shape, id=ids[n], folder=part.folder if part is not None else '',
                        meta=dict(enclosure_mount_of=recipe['target'], enclosure_mount_step=recipe.get('id'))).prepared())
    return out


class EnclosurePanelTools:
    def _build_encpanel_panel(self):
        self.pn = dict(target=None, face=None, items=[], sel=None, picking=False)
        self._pn_timer = QTimer(self)
        self._pn_timer.setSingleShot(True)
        self._pn_timer.setInterval(400)
        self._pn_timer.timeout.connect(lambda: self._pn_exact())
        self.pn_panel, lay = self._panel(320, 'Panel sterowania', 'x_encpanel', 'Powierzchnia → elementy → rozmieszczenie', plain=True, scroll=True)
        self.pn_step1 = ui.StepRow(1, 'x_enclosure', 'Zewnętrzna powierzchnia', plain=True)
        lay.addWidget(self.pn_step1)
        self.pn_step2 = ui.StepRow(2, 'x_encpanel', 'Element', plain=True)
        lay.addWidget(self.pn_step2)
        self.pn_kind = QComboBox()
        for key in pn.ELEMENTS:
            self.pn_kind.addItem(pn.ELEMENT_LABELS[key], key)
        self.pn_kind.currentIndexChanged.connect(lambda *_: self._pn_fields())
        lay.addWidget(self.pn_kind)
        self.pn_c = {}
        for key, items in CHOICES.items():
            box = QComboBox()
            for k_, title in items:
                box.addItem(title, k_)
            box.currentIndexChanged.connect(lambda *_: self._pn_edit())
            lay.addWidget(box)
            self.pn_c[key] = box
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        self.pn_f = {}
        keys = ['u', 'v', 'angle', 'clearance'] + sorted({k for f in FIELDS.values() for k in f}, key=list(TITLES).index)
        for n, key in enumerate(keys):
            box = _spin(float(pn.DEFAULTS[key]), -1e4 if key in ('u', 'v', 'angle', 'module_du', 'module_dv', 'frame_l', 'frame_r', 'frame_t', 'frame_b', 'bend') else 0.0,
                        1e4, 2, 1 if key == 'angle' else .5, ' °' if key == 'angle' else '' if key in ('sides', 'splines') else ' mm')
            box.valueChanged.connect(lambda *_: self._pn_edit())
            label = _label(TITLES[key], 'label')
            grid.addWidget(label, n, 0)
            grid.addWidget(box, n, 1)
            self.pn_f[key] = (label, box)
        lay.addLayout(grid)
        row = QHBoxLayout()
        for title, fn in (('Dodaj element', lambda: self.pn_add()), ('Z komponentu', lambda: self._pn_pick()), ('Usuń', lambda: self.pn_remove())):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        lay.addLayout(row)
        self.pn_list = QListWidget()
        self.pn_list.setObjectName('enclist')
        self.pn_list.setFixedHeight(100)
        self.pn_list.currentRowChanged.connect(lambda r: self._pn_select(r))
        lay.addWidget(self.pn_list)
        self.pn_step3 = ui.StepRow(3, 'x_encpanel', 'Rozmieszczenie', plain=True)
        lay.addWidget(self.pn_step3)
        self.pn_arr = QComboBox()
        for k_, title in (('left', 'Wyrównaj do lewej'), ('right', 'Wyrównaj do prawej'), ('top', 'Wyrównaj do góry'), ('bottom', 'Wyrównaj do dołu'),
                          ('hcenter', 'Wyrównaj w poziomie (środek)'), ('vcenter', 'Wyrównaj w pionie (środek)'), ('center', 'Wyśrodkuj na powierzchni'),
                          ('mirror', 'Symetria względem osi pionowej'), ('hspace', 'Równy rozstaw w poziomie'), ('vspace', 'Równy rozstaw w pionie'),
                          ('array', 'Szyk: 3 kopie ostatniego elementu')):
            self.pn_arr.addItem(title, k_)
        lay.addWidget(self.pn_arr)
        arr = QPushButton('Rozmieść')
        arr.clicked.connect(lambda _=False: self.pn_arrange(self.pn_arr.currentData()))
        lay.addWidget(arr)
        self.pn_info = _label('', 'value')
        lay.addWidget(self.pn_info)
        self.pn_status = _label('Kliknij zewnętrzną płaską powierzchnię obudowy.', 'status')
        lay.addWidget(self.pn_status)
        self.pn_apply, _ = self._buttons(self.pn_panel.footer, 'Zastosuj', 'Anuluj', self.apply_encpanel, lambda: self.set_mode(None))
        self._pn_fields()
        return self.pn_panel

    def _encpanel_begin(self):
        self.pn = dict(target=None, face=None, items=[], sel=None, picking=False)
        self.pn_panel.show()
        self.pn_list.clear()
        if not enclosure_bodies(self.document.bodies):
            self.toast('W projekcie nie ma obudowy z Generatora obudów - najpierw Utwórz obudowę.')
        self.hint('Panel sterowania: kliknij zewnętrzną powierzchnię obudowy i dodawaj elementy.')
        self.view.setCursor(Qt.PointingHandCursor)
        self._pn_update()

    def _pn_fields(self):
        kind = self.pn_kind.currentData()
        show = set(FIELDS.get(kind, ())) | {'u', 'v', 'angle', 'clearance'}
        for key, (label, box) in self.pn_f.items():
            label.setVisible(key in show)
            box.setVisible(key in show)
        vis = {'mount': kind in ('display', 'touch'), 'knob': kind == 'knob', 'bore': kind == 'knob', 'pipe': kind == 'lightpipe',
               'shape': kind == 'button', 'pattern': kind == 'speaker'}
        for key, box in self.pn_c.items():
            box.setVisible(vis[key])
        self._pn_edit()

    def _pn_item(self):
        kind = self.pn_kind.currentData()
        it = dict(element=kind)
        for key in set(FIELDS.get(kind, ())) | {'u', 'v', 'angle', 'clearance'}:
            it[key] = int(self.pn_f[key][1].value()) if key in ('sides', 'splines') else float(self.pn_f[key][1].value())
        for key, box in self.pn_c.items():
            if box.isVisible() or key in ('mount',):
                it[key] = box.currentData()
        if self.pn.get('comp_depth') is not None and kind in ('button', 'lightpipe'):
            it['component_depth'] = self.pn['comp_depth']
        return it

    def pn_add(self):
        self.pn['items'].append(self._pn_item())
        self.pn['sel'] = len(self.pn['items']) - 1
        self._pn_update()

    def pn_remove(self):
        sel = self.pn.get('sel')
        if sel is not None and 0 <= sel < len(self.pn['items']):
            del self.pn['items'][sel]
            self.pn['sel'] = None
            self._pn_update()

    def pn_arrange(self, mode):
        value = 0.0
        if mode == 'array':
            value = 3
        self.pn['items'] = pn.arrange(self.pn['items'], mode, value)
        self._pn_update()

    def _pn_edit(self):
        sel = self.pn.get('sel')
        if sel is not None and 0 <= sel < len(self.pn.get('items') or []) and self.pn['items'][sel]['element'] == self.pn_kind.currentData():
            self.pn['items'][sel] = self._pn_item()          # pola edytują wybrany element
        self._pn_update()

    def _pn_select(self, row):
        self.pn['sel'] = row if row >= 0 else None
        if self.pn['sel'] is None:
            return
        it = self.pn['items'][row]
        widgets = [self.pn_kind, *self.pn_c.values(), *[b for _l, b in self.pn_f.values()]]
        for w_ in widgets:
            w_.blockSignals(True)
        self.pn_kind.setCurrentIndex(self.pn_kind.findData(it['element']))
        for key, box in self.pn_c.items():
            if key in it:
                box.setCurrentIndex(max(0, box.findData(it[key])))
        for key, (_l, box) in self.pn_f.items():
            if key in it:
                box.setValue(float(it[key]))
        for w_ in widgets:
            w_.blockSignals(False)
        self._pn_fields()

    def _pn_pick(self):
        self.pn['picking'] = True
        self.pn_status.setText('Kliknij komponent - element stanie w środku jego rzutu na powierzchnię.')

    def encpanel_hover(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        self.view.set_hover_mesh(body.mesh if body is not None and self.pn.get('picking') else None)

    def encpanel_click(self, x, y, shift=False):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None:
            return
        if self.pn.get('picking') and self.pn.get('face'):
            fr = pn.frame_of(self.pn['face'])
            uv, depth, _lo, _hi = pn.from_component(fr, body.shape.wrapped)
            for key, val in (('u', uv[0]), ('v', uv[1])):
                self.pn_f[key][1].blockSignals(True)
                self.pn_f[key][1].setValue(float(val))
                self.pn_f[key][1].blockSignals(False)
            self.pn['comp_depth'] = float(depth)
            self.pn['picking'] = False
            self._pn_edit()
            return
        if not (body.meta or {}).get('enclosure') or body.kind != 'solid':
            self.toast('Kliknij zewnętrzną powierzchnię części obudowy.')
            return
        face, _n = self.view.face_at(body, hit)
        if face is None or not kernel.is_planar_face(face):
            self.toast('Panel powstaje na płaskiej powierzchni.')
            return
        n = np.asarray(face.normalAt(face.Center()).toTuple(), float)
        self.pn.update(target=body.id, face=dict(point=[float(c) for c in face.Center().toTuple()], normal=[float(c) for c in n]))
        self._pn_update()

    def pn_recipe(self):
        if not self.pn.get('target') or not self.pn.get('face') or not self.pn.get('items'):
            return None
        return dict(type='enc_panel', target=self.pn['target'], face=dict(self.pn['face']), items=[dict(it) for it in self.pn['items']])

    def _pn_update(self):
        if not hasattr(self, 'pn_list') or self.mode != 'encpanel':
            return
        tb = self.document.get(self.pn.get('target') or '')
        self.pn_step1.set_state('done' if tb else 'active', tb.name if tb else 'kliknij powierzchnię')
        self.pn_step2.set_state('done' if self.pn['items'] else ('active' if tb else 'pending'), f'{len(self.pn["items"])} el.')
        self.pn_list.blockSignals(True)
        self.pn_list.clear()
        for k_, it in enumerate(self.pn['items']):
            self.pn_list.addItem(f'{k_ + 1}. {pn.ELEMENT_LABELS[it["element"]]} ({it.get("u", 0):.1f}, {it.get("v", 0):.1f})')
        if self.pn.get('sel') is not None and self.pn['sel'] < self.pn_list.count():
            self.pn_list.setCurrentRow(self.pn['sel'])
        self.pn_list.blockSignals(False)
        self.pn_apply.setEnabled(False)
        self._pn_timer.stop()
        recipe = self.pn_recipe()
        if recipe is None:
            self.view.set_preview_mesh(None)
            return
        self._pn_sig = repr(recipe)
        self.pn_status.setText('Liczenie panelu…')
        self._pn_timer.start()

    def _pn_exact(self):
        recipe = self.pn_recipe()
        if recipe is None or self.mode != 'encpanel':
            return
        sig = repr(recipe)
        bodies = list(self.document.bodies)

        def compute():
            res = build(bodies, recipe)
            from .enclosure import merge_meshes
            return dict(mesh=merge_meshes([kernel.display_mesh(res['part'])] + [kernel.display_mesh(s) for _n, s in res['parts']]),
                        report=res['report'], n=len(res['parts']))

        def show(value, error):
            if self.mode != 'encpanel' or getattr(self, '_pn_sig', None) != sig:
                return
            if error or value is None:
                self.pn_status.setText(str(error) if error else 'Nie udało się policzyć panelu.')
                return
            self.view.set_preview_mesh(value['mesh'], color=(.8, .65, .95, .35), line_color=PANEL_LINE, width=1.2)
            self.pn_info.setText('\n'.join(t for _l, t in value['report']) + (f'\nOsobne bryły: {value["n"]}' if value['n'] else ''))
            self.pn_status.setText('Enter albo Zastosuj tworzy panel.')
            self.pn_apply.setEnabled(True)
        self.run_preview('encpanel', compute, show)

    def _step_fill_enc_panel(self, recipe):
        self.pn.update(target=recipe['target'], face=dict(recipe['face']), items=[dict(it) for it in recipe['items']], sel=None)
        self._pn_update()

    def apply_encpanel(self):
        if self.busy or self.mode != 'encpanel' or not self.pn_apply.isEnabled():
            return
        recipe = self.pn_recipe()
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
            self.document.pending_label = 'Panel sterowania'
            self.document.pending_icon = 'encpanel'
            self.document.commit(bodies)

        def after():
            self.view.set_preview_mesh(None)
            self._pn_update()

        self._pn_timer.stop()
        self.view.set_preview_mesh(None)
        self.run_operation('Panel sterowania', build_step, apply, after=after)
