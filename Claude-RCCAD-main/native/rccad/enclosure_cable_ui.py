"""Generator obudów - etap 20 (okno): „Prowadzenie przewodów” (Obudowy → Prowadzenie przewodów).

Kliknięcie części obudowy, potem punktów: początek i koniec (na komponentach - kierunek wyjścia ze złącza = normalna
ściany, punkt przypięty do komponentu i idzie za nim po jego przesunięciu), punkty pośrednie. Rodzaj, tryb, parametry,
uchwyty. Lista przewodów obudowy (nazwa, kolor, średnica, długość, zapas, punkty, „wymaga aktualizacji” po przesunięciu
komponentu). Wyznaczanie w tle z przyciskiem Przerwij. Zastosuj / Enter - krok 'enc_cable' (przewód = osobna bryła,
uchwyty połączone z częścią; edycja, cofanie, regeneracja z zachowaniem ręcznych punktów pośrednich)."""
from __future__ import annotations

import uuid

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLineEdit, QListWidget, QPushButton, QSpinBox

from . import enclosure_cables as cb
from . import kernel
from . import shell_ui as ui
from .enclosure_ui import _label, _spin
from .enclosure_hole_ui import enclosure_bodies
from .enclosure_rib_ui import _context

CABLE_LINE = (.8, .2, .2, 1)
_CANCEL = {'flag': False}


def _bbmin(shape):
    import cadquery as cq
    bb = cq.Shape.cast(shape).BoundingBox()
    return np.array([bb.xmin, bb.ymin, bb.zmin])


def hex_rgb(value):
    """'#RRGGBB' → (R, G, B) 0..1; inny zapis - None (kolor domyślny)."""
    v = str(value or '').strip()
    try:
        if v.startswith('#') and len(v) == 7:
            return tuple(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except ValueError:
        pass
    return None


def endpoint(bodies, ep):
    """Punkt końcowy: przypięty do komponentu (przesunięcie względem jego ramki) albo stały punkt świata."""
    by_id = {b.id: b for b in bodies}
    if ep.get('comp') and ep['comp'] in by_id:
        return _bbmin(by_id[ep['comp']].shape.wrapped) + np.asarray(ep['offset'], float), np.asarray(ep['dir'], float) if ep.get('dir') else None
    return np.asarray(ep['point'], float), (np.asarray(ep['dir'], float) if ep.get('dir') else None)


def stale(bodies, recipe):
    """Trasa wymaga aktualizacji: komponent końca przesunął się względem zapisanego położenia."""
    by_id = {b.id: b for b in bodies}
    for key in ('start', 'end'):
        ep = recipe.get(key) or {}
        if ep.get('comp') in by_id and ep.get('bbmin') is not None:
            if np.linalg.norm(_bbmin(by_id[ep['comp']].shape.wrapped) - np.asarray(ep['bbmin'], float)) > 1e-6:
                return True
    return False


def build(bodies, recipe, cancel=None):
    from .enclosure_library import _cavity
    part, spec, env, lay, comps, others = _context(bodies, recipe['target'])
    by_id = {b.id: b for b in bodies}
    p = dict(cb.DEFAULTS, **recipe['params'])
    cavity = _cavity(env, spec, lay)
    obstacles = [(by_id[s.id].name, by_id[s.id].shape.wrapped) for s in spec.sources if s.id in by_id and by_id[s.id].kind == 'solid']
    obstacles.append((part.name, part.shape.wrapped))
    for o in others:
        obstacles.append(('pokrywa / inna część', o))
    own = set(recipe.get('out_ids') or [])
    if p.get('avoid_cables', True):
        for b in bodies:
            if (b.meta or {}).get('enclosure_cable_of') == recipe['target'] and b.id not in own:
                if p.get('bundle') and (b.meta or {}).get('bundle') == p.get('bundle'):
                    continue                                  # wspólna wiązka / kanał - bez odpychania
                obstacles.append((b.name, b.shape.wrapped))
    s, sd = endpoint(bodies, recipe['start'])
    e, ed = endpoint(bodies, recipe['end'])
    names = tuple(by_id[x['comp']].name for x in (recipe['start'], recipe['end']) if x.get('comp') in by_id)
    res = cb.route(cavity, obstacles, s, e, p, [np.asarray(w, float) for w in recipe.get('waypoints') or []], sd, ed, names, cancel)
    clips = cb.clips(part.shape.wrapped, res, p, [o for nm, o in obstacles if nm in {by_id[x.id].name for x in spec.sources if x.id in by_id}])
    return res, clips


def run(bodies, recipe):
    """Krok 'enc_cable': przewód (osobna bryła, id z przepisu) i uchwyty (połączone z częścią obudowy)."""
    from dataclasses import replace
    from .document import Body
    from .enclosure import _single, _unified, check_solid
    from .enclosure_ribs import _multi
    res, clips = build(bodies, recipe)
    ids = list(recipe.get('out_ids') or [])
    if not ids:
        ids = [uuid.uuid4().hex]
    recipe['out_ids'] = ids[:1]
    by_id = {b.id: b for b in bodies}
    for key in ('start', 'end'):                              # zapamiętane położenie komponentów (wykrywanie przesunięcia)
        ep = recipe[key]
        if ep.get('comp') in by_id:
            ep['bbmin'] = [float(x) for x in _bbmin(by_id[ep['comp']].shape.wrapped)]
    p = dict(cb.DEFAULTS, **recipe['params'])
    from .enclosure_param import group
    tb = by_id[recipe['target']]
    spec_src = [x['id'] for x in (tb.meta or {}).get('enclosure', {}).get('sources', [])]
    recipe['reads'] = sorted({*spec_src, *(b.id for b in group(bodies, tb) if b.id != tb.id and b.id not in ids)})
    out, part = [], None
    for b in bodies:
        if b.id in ids:
            continue
        if b.id == recipe['target']:
            shape = b.shape
            if clips:
                shape = check_solid(_single(_unified(_multi('fuse', b.shape.wrapped, clips, 'uchwyty przewodu')), 'Obudowa z uchwytami'))
            meta = dict(b.meta or {})
            info = {k: recipe[k] for k in recipe if k != 'type'}
            info.update(length=res['length'], total=res['total'])
            meta['enclosure_cables'] = [*[r for r in meta.get('enclosure_cables', []) if r.get('id') != recipe.get('id')], info]
            b = replace(b, shape=shape, meta=meta, mesh=None).prepared()
            part = b
        out.append(b)
    import cadquery as cq
    rgb = hex_rgb(p.get('color'))
    out.append(Body(p.get('name') or 'Przewód', cq.Shape.cast(res['solid']), id=ids[0], folder=part.folder if part is not None else '', color=rgb,
                    meta=dict(enclosure_cable_of=recipe['target'], enclosure_mount_of=recipe['target'], enclosure_mount_step=recipe.get('id'),
                              bundle=p.get('bundle') or '', length=res['length'], total=res['total'])).prepared())
    return out


class EnclosureCableTools:
    def _build_enccable_panel(self):
        self.cbs = dict(target=None, start=None, end=None, waypoints=[], pick='start')
        self._cb_timer = QTimer(self)
        self._cb_timer.setSingleShot(True)
        self._cb_timer.setInterval(500)
        self._cb_timer.timeout.connect(lambda: self._cb_exact())
        self.cb_panel, lay = self._panel(320, 'Prowadzenie przewodów', 'x_enccable', 'Część → punkty → przewód', plain=True, scroll=True)
        self.cb_step1 = ui.StepRow(1, 'x_enclosure', 'Część obudowy', plain=True)
        lay.addWidget(self.cb_step1)
        self.cb_step2 = ui.StepRow(2, 'x_enccable', 'Punkty: początek, koniec, pośrednie', plain=True)
        lay.addWidget(self.cb_step2)
        row = QHBoxLayout()
        for key, title in (('start', 'Początek'), ('end', 'Koniec'), ('via', 'Pośredni'), ('clear', 'Wyczyść pośr.')):
            b = QPushButton(title)
            b.clicked.connect(lambda _=False, k_=key: self._cb_pickmode(k_))
            row.addWidget(b)
        lay.addLayout(row)
        self.cb_name = QLineEdit('Przewód')
        self.cb_name.editingFinished.connect(lambda: self._cb_update())
        lay.addWidget(self.cb_name)
        self.cb_color = QLineEdit('#c0392b')
        self.cb_color.setToolTip('Kolor przewodu (#RRGGBB)')
        lay.addWidget(self.cb_color)
        self.cb_bundle = QLineEdit('')
        self.cb_bundle.setPlaceholderText('Wiązka / wspólny kanał (nazwa - przewody o tej samej nazwie się nie odpychają)')
        lay.addWidget(self.cb_bundle)
        self.cb_c = {}
        for key, items in (('kind', cb.KIND_LABELS), ('mode', cb.MODE_LABELS), ('clip', cb.CLIP_LABELS), ('direction', cb.DIRECTION_LABELS)):
            box = QComboBox()
            for k_, title in items.items():
                box.addItem(title, k_)
            box.currentIndexChanged.connect(lambda *_: self._cb_update())
            lay.addWidget(box)
            self.cb_c[key] = box
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        d = cb.DEFAULTS
        rows = (('diameter', 'Średnica przewodu'), ('width', 'Szerokość (płaski)'), ('thickness', 'Grubość (płaski)'), ('sleeve', 'Grubość osłony'),
                ('inner', 'Średnica wewnętrzna (rurka)'), ('min_bend', 'Min. promień gięcia'), ('clearance', 'Min. odstęp od przeszkód'),
                ('wall_gap', 'Odstęp od ścianek'), ('straight', 'Odcinek prosty przy złączu'), ('spare', 'Zapas długości [%]'),
                ('max_len', 'Maks. długość (0 = bez)'), ('clip_pitch', 'Rozstaw uchwytów'), ('clip_t', 'Grubość uchwytu'), ('clip_w', 'Szerokość uchwytu'),
                ('reach', 'Zasięg do powierzchni montażowej'), ('resolution', 'Rozdzielczość siatki (0 = auto)'))
        self.cb_f = {}
        for n, (key, title) in enumerate(rows):
            box = _spin(float(d[key]), 0.0, 1e4, 2, .5, ' %' if key == 'spare' else ' mm')
            box.valueChanged.connect(lambda *_: self._cb_update())
            label = _label(title, 'label')
            grid.addWidget(label, n, 0)
            grid.addWidget(box, n, 1)
            self.cb_f[key] = (label, box)
        self.cb_count = QSpinBox()
        self.cb_count.setRange(1, 200)
        self.cb_count.setValue(int(d['count']))
        self.cb_count.valueChanged.connect(lambda *_: self._cb_update())
        grid.addWidget(_label('Liczba przewodów w wiązce', 'label'), len(rows), 0)
        grid.addWidget(self.cb_count, len(rows), 1)
        lay.addLayout(grid)
        self.cb_spline = QCheckBox('Wygładzanie B-spline (z kontrolą krzywizny)')
        self.cb_spline.toggled.connect(lambda *_: self._cb_update())
        lay.addWidget(self.cb_spline)
        self.cb_avoid = QCheckBox('Omijaj inne przewody')
        self.cb_avoid.setChecked(True)
        self.cb_avoid.toggled.connect(lambda *_: self._cb_update())
        lay.addWidget(self.cb_avoid)
        stop = QPushButton('Przerwij obliczenia')
        stop.clicked.connect(lambda _=False: _CANCEL.update(flag=True))
        lay.addWidget(stop)
        lay.addWidget(_label('Przewody w obudowie:', 'label'))
        self.cb_list = QListWidget()
        self.cb_list.setObjectName('enclist')
        self.cb_list.setFixedHeight(96)
        lay.addWidget(self.cb_list)
        self.cb_info = _label('', 'value')
        lay.addWidget(self.cb_info)
        self.cb_status = _label('Kliknij część obudowy.', 'status')
        lay.addWidget(self.cb_status)
        self.cb_apply, _ = self._buttons(self.cb_panel.footer, 'Zastosuj', 'Anuluj', self.apply_enccable, lambda: self.set_mode(None))
        return self.cb_panel

    def _enccable_begin(self):
        self.cbs = dict(target=None, start=None, end=None, waypoints=[], pick='start')
        self.cb_panel.show()
        if not enclosure_bodies(self.document.bodies):
            self.toast('W projekcie nie ma obudowy z Generatora obudów - najpierw Utwórz obudowę.')
        self.hint('Prowadzenie przewodów: kliknij część obudowy, potem początek i koniec przewodu (na złączach komponentów).')
        self.view.setCursor(Qt.PointingHandCursor)
        self._cb_update()

    def _cb_pickmode(self, key):
        if key == 'clear':
            self.cbs['waypoints'] = []
            self._cb_update()
            return
        self.cbs['pick'] = key
        self.cb_status.setText({'start': 'Kliknij początek (ścianę złącza).', 'end': 'Kliknij koniec (ścianę złącza).',
                                'via': 'Klikaj punkty pośrednie (na powierzchniach - punkt odsunięty od nich).'}[key])

    def enccable_hover(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        self.view.set_hover_mesh(body.mesh if body is not None else None)

    def enccable_click(self, x, y, shift=False):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None:
            return
        if self.cbs.get('target') is None:
            if not (body.meta or {}).get('enclosure') or body.kind != 'solid':
                self.toast('Najpierw kliknij część obudowy, w której ma biec przewód.')
                return
            self.cbs['target'] = body.id
            self._cb_update()
            return
        pt, n = np.asarray(hit[2], float), np.asarray(hit[1], float)
        key = self.cbs.get('pick', 'start')
        if key == 'via':
            off = cb.cable_radius(self.cb_params()) + float(self.cb_f['clearance'][1].value()) + 1.0
            self.cbs['waypoints'].append([float(c) for c in pt + n * off])
        else:
            ep = dict(point=[float(c) for c in pt], dir=[float(c) for c in n])
            if not (body.meta or {}).get('enclosure'):             # na komponencie - punkt przypięty do niego
                ep.update(comp=body.id, offset=[float(c) for c in pt - _bbmin(body.shape.wrapped)])
            self.cbs[key] = ep
            self.cbs['pick'] = 'end' if key == 'start' else 'via'
        self._cb_update()

    def cb_params(self):
        out = {k: float(b.value()) for k, (_l, b) in self.cb_f.items()}
        out.update({k: b.currentData() for k, b in self.cb_c.items()})
        out.update(count=self.cb_count.value(), spline=self.cb_spline.isChecked(), avoid_cables=self.cb_avoid.isChecked(),
                   name=self.cb_name.text() or 'Przewód', color=self.cb_color.text(), bundle=self.cb_bundle.text())
        return out

    def cb_recipe(self):
        if not self.cbs.get('target') or not self.cbs.get('start') or not self.cbs.get('end'):
            return None
        return dict(type='enc_cable', target=self.cbs['target'], start=dict(self.cbs['start']), end=dict(self.cbs['end']),
                    waypoints=[list(w) for w in self.cbs['waypoints']], params=self.cb_params(), out_ids=list(self.cbs.get('out_ids') or []))

    def _cb_list_fill(self):
        self.cb_list.clear()
        tb = self.document.get(self.cbs.get('target') or '')
        if tb is None:
            return
        for r in (tb.meta or {}).get('enclosure_cables', []):
            prm = r.get('params') or {}
            flag = ' - wymaga aktualizacji' if stale(self.document.bodies, r) else ''
            self.cb_list.addItem(f'{prm.get("name", "Przewód")} ({prm.get("color", "")}), Ø{float(prm.get("diameter", 0)):g} mm, '
                                 f'{float(r.get("length", 0)):.0f} mm (+{float(prm.get("spare", 0)):g} %), punkty pośr.: {len(r.get("waypoints") or [])}{flag}')

    def _cb_update(self):
        if not hasattr(self, 'cb_c') or self.mode != 'enccable':
            return
        tb = self.document.get(self.cbs.get('target') or '')
        self.cb_step1.set_state('done' if tb else 'active', tb.name if tb else 'kliknij część')
        have = ('start' if self.cbs.get('start') else '') + (' + koniec' if self.cbs.get('end') else '')
        self.cb_step2.set_state('done' if self.cbs.get('end') else ('active' if tb else 'pending'), (have or 'kliknij') + f', pośr.: {len(self.cbs["waypoints"])}')
        self._cb_list_fill()
        self.cb_apply.setEnabled(False)
        self._cb_timer.stop()
        recipe = self.cb_recipe()
        if recipe is None:
            self.view.set_preview_mesh(None)
            return
        self._cb_sig = repr(recipe)
        self.cb_status.setText('Wyznaczanie trasy…')
        self._cb_timer.start()

    def _cb_exact(self):
        recipe = self.cb_recipe()
        if recipe is None or self.mode != 'enccable':
            return
        sig = repr(recipe)
        bodies = list(self.document.bodies)
        _CANCEL['flag'] = False

        def compute():
            res, clips = build(bodies, recipe, cancel=lambda: _CANCEL['flag'])
            import cadquery as cq
            from .enclosure import merge_meshes
            return dict(mesh=merge_meshes([kernel.display_mesh(cq.Shape.cast(res['solid']))] + [kernel.display_mesh(cq.Shape.cast(c)) for c in clips]),
                        report=res['report'], clips=len(clips))

        def show(value, error):
            if self.mode != 'enccable' or getattr(self, '_cb_sig', None) != sig:
                return
            if error or value is None:
                self.cb_status.setText(str(error) if error else 'Nie udało się wyznaczyć trasy.')
                return
            self.view.set_preview_mesh(value['mesh'], color=(.9, .3, .3, .55), line_color=CABLE_LINE, width=1.2)
            self.cb_info.setText('\n'.join(t for _l, t in value['report']) + (f'\nUchwyty: {value["clips"]}' if value['clips'] else ''))
            self.cb_status.setText('Enter albo Zastosuj dodaje przewód.')
            self.cb_apply.setEnabled(True)
        self.run_preview('enccable', compute, show)

    def _step_fill_enc_cable(self, recipe):
        p = dict(cb.DEFAULTS, **recipe['params'])
        self.cbs.update(target=recipe['target'], start=dict(recipe['start']), end=dict(recipe['end']), waypoints=[list(w) for w in recipe.get('waypoints') or []],
                        out_ids=list(recipe.get('out_ids') or []))
        for k_, box in self.cb_c.items():
            box.blockSignals(True)
            box.setCurrentIndex(max(0, box.findData(p[k_])))
            box.blockSignals(False)
        for k_, (_l, box) in self.cb_f.items():
            box.blockSignals(True)
            box.setValue(float(p[k_]))
            box.blockSignals(False)
        self.cb_name.setText(p['name'])
        self.cb_color.setText(p['color'])
        self.cb_bundle.setText(p.get('bundle') or '')
        self._cb_update()

    def apply_enccable(self):
        if self.busy or self.mode != 'enccable' or not self.cb_apply.isEnabled():
            return
        recipe = self.cb_recipe()
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
            self.document.pending_label = 'Prowadzenie przewodów'
            self.document.pending_icon = 'enccable'
            self.document.commit(bodies)

        def after():
            self.view.set_preview_mesh(None)
            self.cbs.update(start=None, end=None, waypoints=[], pick='start', out_ids=[])
            self._cb_update()

        self._cb_timer.stop()
        self.view.set_preview_mesh(None)
        self.run_operation('Prowadzenie przewodów', build_step, apply, after=after)
