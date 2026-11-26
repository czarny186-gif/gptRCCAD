"""Generator obudów - etap 18 (okno): „Przegrody wewnętrzne” (Obudowy → Przegrody wewnętrzne).

Kliknięcie części obudowy (w trybie „równolegle do ściany” - jej ściany, „przez dwa punkty” - dwóch punktów), rodzaj,
położenie, parametry, przepusty, komory (liczba / wymiary / udziały / propozycja według komponentów - tylko położenia
przegród, komponenty zostają na miejscu) i przypisanie komponentów do komór. Podgląd dokładny w tle. Zastosuj / Enter -
krok 'enc_part' (parametry zapisane, edycja, cofanie, regeneracja). Geometria: rccad.enclosure_partitions."""
from __future__ import annotations

import uuid

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QGridLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox

from . import enclosure_partitions as ep
from . import kernel
from . import shell_ui as ui
from .enclosure_ui import _label, _spin
from .enclosure_hole_ui import enclosure_bodies
from .enclosure_rib_ui import _context

PART_LINE = (.15, .6, .35, 1)


def build(bodies, recipe):
    part, spec, env, lay, comps, others = _context(bodies, recipe['target'])
    by_id = {b.id: b for b in bodies}
    ids = [s.id for s in spec.sources if s.id in by_id and by_id[s.id].kind == 'solid']
    sk = None
    sid = (recipe.get('params') or {}).get('sketch')
    if sid:
        sb = by_id.get(sid)
        if sb is None or sb.kind != 'sketch':
            raise kernel.CadError('Szkicu z linią przegrody już nie ma.')
        sk = sb.shape.wrapped
    return ep.build_many(part.shape, spec, env, lay, recipe['params'], comps, others, sk, ids)


def run(bodies, recipe):
    """Krok 'enc_part': przegrody - część obudowy z przegrodą / prowadnicami, przegrody wyjmowane jako osobne bryły."""
    from dataclasses import replace
    from .document import Body
    res = build(bodies, recipe)
    ids = list(recipe.get('out_ids') or [])
    while len(ids) < len(res['separate']):
        ids.append(uuid.uuid4().hex)
    old = set(recipe.get('out_ids') or [])
    recipe['out_ids'] = ids[:len(res['separate'])]
    out, part = [], None
    for b in bodies:
        if b.id in old:
            continue
        if b.id == recipe['target']:
            meta = dict(b.meta or {})
            meta['enclosure_parts'] = [*[r for r in meta.get('enclosure_parts', []) if r.get('id') != recipe.get('id')],
                                       {k: recipe[k] for k in recipe if k != 'type'}]
            b = replace(b, shape=res['part'], meta=meta, mesh=None).prepared()
            part = b
        out.append(b)
    for n, shape in enumerate(res['separate']):
        out.append(Body(f'Przegroda wyjmowana {n + 1}', shape, id=ids[n], folder=part.folder if part is not None else '',
                        meta=dict(enclosure_mount_of=recipe['target'], enclosure_mount_step=recipe.get('id'))).prepared())
    return out


class EnclosurePartitionTools:
    def _build_encpart_panel(self):
        self.ep = dict(target=None, face=None, p1=None, p2=None, assign={})
        self._ep_timer = QTimer(self)
        self._ep_timer.setSingleShot(True)
        self._ep_timer.setInterval(350)
        self._ep_timer.timeout.connect(lambda: self._ep_exact())
        self.ep_panel, lay = self._panel(312, 'Przegrody wewnętrzne', 'x_encpart', 'Część → położenie → rodzaj', plain=True, scroll=True)
        self.ep_step1 = ui.StepRow(1, 'x_enclosure', 'Część obudowy', plain=True)
        lay.addWidget(self.ep_step1)
        self.ep_step2 = ui.StepRow(2, 'x_encpart', 'Położenie i rodzaj', plain=True)
        lay.addWidget(self.ep_step2)
        self.ep_c = {}
        for key, items in (('place', ep.PLACE_LABELS), ('axis', {'x': 'Oś X obudowy', 'y': 'Oś Y obudowy', 'z': 'Oś Z obudowy'}),
                           ('kind', ep.KIND_LABELS), ('pass_kind', ep.PASS_LABELS),
                           ('mode', {'single': 'Jedna przegroda', 'count': 'Komory: liczba', 'sizes': 'Komory: wymiary [mm]',
                                     'percent': 'Komory: udziały [%]', 'components': 'Komory: propozycja według komponentów'})):
            box = QComboBox()
            for k_, title in items.items():
                box.addItem(title, k_)
            box.currentIndexChanged.connect(lambda *_: self._ep_update())
            lay.addWidget(box)
            self.ep_c[key] = box
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        d = ep.DEFAULTS
        rows = (('offset', 'Odległość od ścianki / ściany', 0.0), ('percent', 'Położenie w % (0 = odległość)', 0.0), ('thickness', 'Grubość', .3),
                ('height', 'Wysokość (0 = do pokrywy)', 0.0), ('length', 'Długość (0 = pełna)', 0.0), ('angle', 'Kąt nachylenia', -89.0),
                ('radius', 'Promień (zakrzywiona)', 1.0), ('gap_bottom', 'Odstęp od dna', 0.0), ('gap_top', 'Odstęp od pokrywy', 0.0),
                ('clearance', 'Luz montażowy (wyjmowana)', 0.0), ('comp_gap', 'Min. odstęp od komponentów', 0.0),
                ('pass_w', 'Przepust - szerokość / średnica', .5), ('pass_h', 'Przepust - wysokość', .5), ('pass_u', 'Przepust - w bok', -1e4),
                ('pass_v', 'Przepust - w górę', -1e4), ('guide_w', 'Prowadnica - szerokość listwy', .3), ('guide_d', 'Prowadnica - głębokość', .2),
                ('width', 'Kanał - szerokość', .5), ('wall_h', 'Kanał kablowy - wysokość ścianek', .5))
        self.ep_f = {}
        for n, (key, title, low) in enumerate(rows):
            box = _spin(d[key], low, 1e4, 2, 1 if key == 'angle' else .5, ' %' if key == 'percent' else ' °' if key == 'angle' else ' mm')
            box.valueChanged.connect(lambda *_: self._ep_update())
            label = _label(title, 'label')
            grid.addWidget(label, n, 0)
            grid.addWidget(box, n, 1)
            self.ep_f[key] = (label, box)
        self.ep_count = QSpinBox()
        self.ep_count.setRange(2, 20)
        self.ep_count.valueChanged.connect(lambda *_: self._ep_update())
        grid.addWidget(_label('Liczba komór', 'label'), len(rows), 0)
        grid.addWidget(self.ep_count, len(rows), 1)
        lay.addLayout(grid)
        self.ep_sizes = QLineEdit()
        self.ep_sizes.setPlaceholderText('Wymiary / udziały komór, np. 30; 40; 30')
        self.ep_sizes.editingFinished.connect(lambda: self._ep_update())
        lay.addWidget(self.ep_sizes)
        lay.addWidget(_label('Komponenty → komora (dwuklik zmienia numer):', 'label'))
        self.ep_list = QListWidget()
        self.ep_list.setObjectName('enclist')
        self.ep_list.setFixedHeight(90)
        self.ep_list.itemDoubleClicked.connect(lambda it: self._ep_cycle(it))
        lay.addWidget(self.ep_list)
        self.ep_info = _label('', 'value')
        lay.addWidget(self.ep_info)
        self.ep_status = _label('Kliknij część obudowy.', 'status')
        lay.addWidget(self.ep_status)
        lay.addWidget(_label(ep.NO_CERT, 'status'))
        self.ep_apply, _ = self._buttons(self.ep_panel.footer, 'Zastosuj', 'Anuluj', self.apply_encpart, lambda: self.set_mode(None))
        return self.ep_panel

    def _encpart_begin(self):
        self.ep = dict(target=None, face=None, p1=None, p2=None, assign={})
        self.ep_panel.show()
        if not enclosure_bodies(self.document.bodies):
            self.toast('W projekcie nie ma obudowy z Generatora obudów - najpierw Utwórz obudowę.')
        self.hint('Przegrody wewnętrzne: kliknij część obudowy, wybierz położenie i rodzaj.')
        self.view.setCursor(Qt.PointingHandCursor)
        self._ep_update()

    def encpart_hover(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        self.view.set_hover_mesh(body.mesh if body is not None and (body.meta or {}).get('enclosure') else None)

    def encpart_click(self, x, y, shift=False):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or not (body.meta or {}).get('enclosure') or body.kind != 'solid':
            self.toast('Kliknij część obudowy z Generatora obudów.')
            return
        place = self.ep_c['place'].currentData()
        if self.ep.get('target') == body.id and place == 'face':
            face, _n = self.view.face_at(body, hit)
            if face is not None and kernel.is_planar_face(face):
                n = np.asarray(face.normalAt(face.Center()).toTuple(), float)
                self.ep['face'] = dict(point=[float(c) for c in face.Center().toTuple()], normal=[float(c) for c in n])
        elif self.ep.get('target') == body.id and place == 'points':
            key = 'p1' if self.ep.get('p1') is None or self.ep.get('p2') is not None else 'p2'
            if key == 'p1':
                self.ep['p2'] = None
            self.ep[key] = [float(c) for c in hit[2]]
        else:
            self.ep.update(target=body.id, face=None, p1=None, p2=None, assign={})
        self._ep_update()

    def _ep_cycle(self, item):
        cid = item.data(Qt.UserRole)
        n = int(self.ep['assign'].get(cid, 0)) + 1
        if n > self._ep_chambers():
            n = 0
        if n:
            self.ep['assign'][cid] = n
        else:
            self.ep['assign'].pop(cid, None)
        self._ep_update()

    def _ep_chambers(self):
        mode = self.ep_c['mode'].currentData()
        return 2 if mode == 'single' else max(2, len(self.ep.get('offsets') or []) + 1)

    def ep_params(self):
        out = {k: float(b.value()) for k, (_l, b) in self.ep_f.items()}
        out.update({k: b.currentData() for k, b in self.ep_c.items() if k != 'mode'})
        out.update(face=self.ep.get('face'), p1=self.ep.get('p1'), p2=self.ep.get('p2'), assign=dict(self.ep.get('assign') or {}),
                   sketch=self.ep.get('sketch'), offsets=list(self.ep.get('offsets') or []))
        return out

    def ep_recipe(self):
        if not self.ep.get('target'):
            return None
        return dict(type='enc_part', target=self.ep['target'], params=self.ep_params())

    def _ep_offsets(self, part):
        """Położenia przegród komór (propozycja - zapisywana jako zwykłe odległości, nic nie przesuwa komponentów)."""
        mode = self.ep_c['mode'].currentData()
        if mode == 'single':
            return []
        _p, spec, env, lay, comps, _o = _context(self.document.bodies, part.id)
        lo, hi = (np.asarray(x, float) for x in lay['inner'])
        sizes = [float(x) for x in self.ep_sizes.text().replace(',', '.').split(';') if x.strip()] if mode in ('sizes', 'percent') else []
        bbs = None
        if mode == 'components':
            import cadquery as cq
            ax, c = np.asarray(env.axes, float), np.asarray(env.center, float)
            bbs = []
            for sh in comps:
                bb = cq.Shape.cast(sh).BoundingBox()
                pts = (np.array([[x, y, z] for x in (bb.xmin, bb.xmax) for y in (bb.ymin, bb.ymax) for z in (bb.zmin, bb.zmax)]) - c) @ ax.T
                bbs.append((pts.min(axis=0), pts.max(axis=0)))
        return ep.chamber_positions(dict(ep.DEFAULTS, axis=self.ep_c['axis'].currentData(), mode=mode, chambers=self.ep_count.value(),
                                         sizes=sizes, thickness=self.ep_f['thickness'][1].value()), lo, hi, bbs)

    def _ep_update(self):
        if not hasattr(self, 'ep_c') or self.mode != 'encpart':
            return
        kind, place, mode = self.ep_c['kind'].currentData(), self.ep_c['place'].currentData(), self.ep_c['mode'].currentData()
        tb = self.document.get(self.ep.get('target') or '')
        self.ep_step1.set_state('done' if tb else 'active', tb.name if tb else 'kliknij część')
        self.ep_step2.set_state('active' if tb else 'pending', ep.KIND_LABELS[kind].lower())
        self.ep_count.setVisible(mode == 'count')
        self.ep_sizes.setVisible(mode in ('sizes', 'percent'))
        self.ep_apply.setEnabled(False)
        self._ep_timer.stop()
        self.ep_list.clear()
        if tb is None:
            return
        try:
            self.ep['offsets'] = self._ep_offsets(tb) if place == 'axis' else []
        except kernel.CadError as exc:
            self.ep_status.setText(str(exc))
            return
        _p, spec, _env, _lay, _c, _o = _context(self.document.bodies, tb.id)
        for s in spec.sources:
            b = self.document.get(s.id)
            if b is None:
                continue
            ch = self.ep['assign'].get(b.id)
            it = QListWidgetItem(f'{b.name} → komora {ch}' if ch else f'{b.name} → (dowolna)')
            it.setData(Qt.UserRole, b.id)
            self.ep_list.addItem(it)
        if self.ep['offsets']:
            self.ep_info.setText('Przegrody w odległościach: ' + ', '.join(f'{x:.1f}' for x in self.ep['offsets']) + ' mm')
        else:
            self.ep_info.setText('')
        self.ep_status.setText('Liczenie przegrody…')
        self._ep_sig = repr(self.ep_recipe())
        self._ep_timer.start()

    def _ep_exact(self):
        recipe = self.ep_recipe()
        if recipe is None or self.mode != 'encpart':
            return
        sig = repr(recipe)
        bodies = list(self.document.bodies)

        def compute():
            res = build(bodies, recipe)
            from .enclosure import merge_meshes
            return dict(mesh=merge_meshes([kernel.display_mesh(res['part'])] + [kernel.display_mesh(s) for s in res['separate']]),
                        report=res['report'], n=len(res['separate']))

        def show(value, error):
            if self.mode != 'encpart' or getattr(self, '_ep_sig', None) != sig:
                return
            if error or value is None:
                self.ep_status.setText(str(error) if error else 'Nie udało się policzyć przegrody.')
                return
            self.view.set_preview_mesh(value['mesh'], color=(.55, .85, .6, .35), line_color=PART_LINE, width=1.2)
            self.ep_status.setText('\n'.join(t for l, t in value['report'] if l != 'info') or 'Enter albo Zastosuj dodaje przegrodę.')
            self.ep_apply.setEnabled(True)
        self.run_preview('encpart', compute, show)

    def _step_fill_enc_part(self, recipe):
        p = dict(ep.DEFAULTS, **recipe['params'])
        self.ep.update(target=recipe['target'], face=p.get('face'), p1=p.get('p1'), p2=p.get('p2'), assign=dict(p.get('assign') or {}),
                       out_ids=list(recipe.get('out_ids') or []))
        for k_, box in self.ep_c.items():
            if k_ in p:
                box.blockSignals(True)
                box.setCurrentIndex(max(0, box.findData(p[k_])))
                box.blockSignals(False)
        for k_, (_l, box) in self.ep_f.items():
            box.blockSignals(True)
            box.setValue(float(p[k_]))
            box.blockSignals(False)
        if p.get('offsets'):
            self.ep_c['mode'].blockSignals(True)
            self.ep_c['mode'].setCurrentIndex(self.ep_c['mode'].findData('sizes'))
            self.ep_c['mode'].blockSignals(False)
            prev, sizes = 0.0, []
            for x in p['offsets']:
                sizes.append(x - prev)
                prev = x
            self.ep_sizes.setText('; '.join(f'{x:g}' for x in sizes))
        self._ep_update()

    def apply_encpart(self):
        if self.busy or self.mode != 'encpart' or not self.ep_apply.isEnabled():
            return
        recipe = self.ep_recipe()
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
            self.document.pending_label = 'Przegrody wewnętrzne'
            self.document.pending_icon = 'encpart'
            self.document.commit(bodies)

        def after():
            self.view.set_preview_mesh(None)
            self._ep_update()

        self._ep_timer.stop()
        self.view.set_preview_mesh(None)
        self.run_operation('Przegrody wewnętrzne', build_step, apply, after=after)
