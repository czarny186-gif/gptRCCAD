"""Okno „Otwór na element” (zakładka Obudowy) - etap 8 Generatora obudów.

Kroki: 1) element - bryła albo ściany komponentu (klik, Shift - kolejne ściany), 2) ścianka obudowy - proponowana
najbliższa płaska ściana przed elementem, do zmiany kliknięciem, i kierunek wycięcia, 3) profil - tryb, biblioteka
złączy, luzy, przesunięcie, obrót, 4) wycięcie - rodzaj, głębokości, miejsce na wtyczkę, dostęp palca, miejsce na
przewód. Podgląd narzędzia liczony w tle (run_preview) - nic nie trafia do dokumentu. Zastosuj: osobny krok historii
„Otwór na element” (Cofnij / Ponów, zapis projektu, przeliczanie). Geometria: rccad.enclosure_holes."""
from __future__ import annotations

import uuid

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QPushButton

from . import enclosure_holes as eh
from . import kernel
from . import shell_ui as ui
from .enclosure_ui import _label, _spin

TOOL_FILL = (.9, .15, .15, .35)
TOOL_LINE = (.75, .05, .05, 1)


def enclosure_bodies(bodies):
    return [b for b in bodies if b.kind == 'solid' and (b.meta or {}).get('enclosure')]


class EnclosureHoleTools:
    def _build_enchole_panel(self):
        self.eh = dict(faces=[], whole=None, target=None, sketch=None, picking='element')
        self.eh_panel, lay = self._panel(300, 'Otwór na element', 'x_enchole', 'Element → ścianka → profil', plain=True, scroll=True)
        self.eh_step1 = ui.StepRow(1, 'x_enchole', 'Element', plain=True)
        lay.addWidget(self.eh_step1)
        self.eh_whole = QCheckBox('Cała bryła (zamiast wskazanych ścian)')
        self.eh_whole.setToolTip('Klik wybiera całą bryłę komponentu; wyłączone - ściany (Shift - kolejne)')
        self.eh_whole.toggled.connect(lambda *_: self._eh_update())
        lay.addWidget(self.eh_whole)
        row = QHBoxLayout()
        self.eh_pick_el = QPushButton('Wskaż element')
        self.eh_pick_el.clicked.connect(lambda _=False: self._eh_pick('element'))
        self.eh_pick_wall = QPushButton('Wskaż ściankę')
        self.eh_pick_wall.setToolTip('Kliknij płaską ścianę obudowy, w której ma powstać otwór')
        self.eh_pick_wall.clicked.connect(lambda _=False: self._eh_pick('wall'))
        row.addWidget(self.eh_pick_el)
        row.addWidget(self.eh_pick_wall)
        lay.addLayout(row)
        self.eh_step2 = ui.StepRow(2, 'x_enclosure', 'Ścianka obudowy', plain=True)
        lay.addWidget(self.eh_step2)
        self.eh_dir = QComboBox()
        self.eh_dir.addItem('Wycięcie prostopadle do ścianki', 'normal')
        self.eh_dir.addItem('Wycięcie wzdłuż osi elementu', 'element')
        self.eh_dir.setToolTip('Kierunek rzutu konturu i wyciągnięcia narzędzia')
        self.eh_dir.currentIndexChanged.connect(lambda *_: self._eh_update())
        lay.addWidget(self.eh_dir)
        self.eh_step3 = ui.StepRow(3, 'x_enchole', 'Profil otworu', plain=True)
        lay.addWidget(self.eh_step3)
        self.eh_mode = QComboBox()
        for m in eh.MODES:
            self.eh_mode.addItem(eh.MODE_LABELS[m], m)
        self.eh_mode.setCurrentIndex(self.eh_mode.findData('rrect'))
        self.eh_mode.currentIndexChanged.connect(lambda *_: self._eh_update())
        lay.addWidget(self.eh_mode)
        self.eh_lib = QComboBox()
        for key, (title, _d) in eh.LIBRARY.items():
            self.eh_lib.addItem(title, key)
        self.eh_lib.currentIndexChanged.connect(lambda *_: self._eh_lib_changed())
        lay.addWidget(self.eh_lib)
        self.eh_sketch_btn = QPushButton('Wskaż szkic z konturem')
        self.eh_sketch_btn.clicked.connect(lambda _=False: self._eh_pick('sketch'))
        lay.addWidget(self.eh_sketch_btn)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        self.eh_f = {}
        rows = (('lw', 'Szerokość profilu', 0.1), ('lh', 'Wysokość profilu', 0.1), ('lb', 'Dolna szerokość', 0.1), ('lr', 'Promień narożników', 0.0),
                ('radius', 'Promień narożników', 0.0),
                ('cl', 'Luz w lewo', 0.0), ('cr', 'Luz w prawo', 0.0), ('cb', 'Luz w dół', 0.0), ('ct', 'Luz w górę', 0.0),
                ('du', 'Przesunięcie w prawo', -1e4), ('dv', 'Przesunięcie w górę', -1e4), ('angle', 'Obrót profilu', -360),
                ('depth', 'Głębokość wycięcia', 0.0), ('step', 'Poszerzenie stopnia', 0.0), ('step_depth', 'Głębokość stopnia', 0.0),
                ('plug', 'Miejsce na wtyczkę (margines)', 0.0), ('plug_depth', 'Głębokość miejsca na wtyczkę', 0.0),
                ('finger', 'Dostęp palca (średnica)', 0.0), ('finger_dv', 'Dostęp palca - przesunięcie w górę', -1e4),
                ('cable', 'Miejsce na przewód (długość)', 0.0))
        d = eh.DEFAULTS
        init = dict(lw=0, lh=0, lb=0, lr=0, radius=d['radius'], cl=d['clear']['l'], cr=d['clear']['r'], cb=d['clear']['b'], ct=d['clear']['t'],
                    du=0, dv=0, angle=0, depth=d['depth'], step=d['step'], step_depth=d['step_depth'], plug=0, plug_depth=d['plug_depth'],
                    finger=0, finger_dv=0, cable=0)
        for n, (key, title, low) in enumerate(rows):
            box = _spin(init[key], low, 1e4, 2, .1 if key not in ('angle',) else 5, ' °' if key == 'angle' else ' mm')
            box.valueChanged.connect(lambda *_: self._eh_update())
            label = _label(title, 'label')
            grid.addWidget(label, n, 0)
            grid.addWidget(box, n, 1)
            self.eh_f[key] = (label, box)
        self.eh_cut = QComboBox()
        for c in eh.CUTS:
            self.eh_cut.addItem(eh.CUT_LABELS[c], c)
        self.eh_cut.currentIndexChanged.connect(lambda *_: self._eh_update())
        self.eh_step4 = ui.StepRow(4, 'x_enchole', 'Wycięcie', plain=True)
        lay.addLayout(grid)
        lay.addWidget(self.eh_step4)
        lay.addWidget(self.eh_cut)
        grid2 = QGridLayout()
        for n, key in enumerate(('depth', 'step', 'step_depth', 'plug', 'plug_depth', 'finger', 'finger_dv', 'cable')):
            label, box = self.eh_f[key]
            grid.removeWidget(label)
            grid.removeWidget(box)
            grid2.addWidget(label, n, 0)
            grid2.addWidget(box, n, 1)
        lay.addLayout(grid2)
        self.eh_status = _label('Kliknij element (bryłę albo jego ściany), dla którego ma powstać otwór.', 'status')
        lay.addWidget(self.eh_status)
        self.eh_apply, _ = self._buttons(self.eh_panel.footer, 'Zastosuj', 'Anuluj', self.apply_enchole, lambda: self.set_mode(None))
        self._eh_lib_changed(update=False)
        return self.eh_panel

    # ------------------------------------------------------------------ tryb
    def _enchole_begin(self):
        self.eh = dict(faces=[], whole=None, target=None, sketch=None, picking='element')
        self._eh_result = None
        self.eh_panel.show()
        if not enclosure_bodies(self.document.bodies):
            self.toast('W projekcie nie ma obudowy z Generatora obudów - najpierw Utwórz obudowę.')
        sel = [i for i in self.selected if (b := self.document.get(i)) is not None and b.kind == 'solid' and not (b.meta or {}).get('enclosure')]
        if sel:
            self.eh_whole.setChecked(True)
            self.eh['whole'] = sel[0]
            self._eh_propose()
        self.hint('Otwór na element: kliknij element (Shift - kolejne ściany), potem sprawdź ściankę obudowy.')
        self.view.setCursor(Qt.PointingHandCursor)
        self._eh_update()

    def _eh_pick(self, what):
        self.eh['picking'] = what
        self.eh_status.setText({'element': 'Kliknij element (bryłę albo ściany - Shift dodaje kolejne).',
                                'wall': 'Kliknij płaską ściankę obudowy.', 'sketch': 'Kliknij zamknięty szkic z konturem otworu.'}[what])

    def _eh_lib_changed(self, update=True):
        lib = eh.LIBRARY[self.eh_lib.currentData()][1]
        for key, src in (('lw', 'w'), ('lh', 'h'), ('lb', 'b'), ('lr', 'r')):
            box = self.eh_f[key][1]
            box.blockSignals(True)
            box.setValue(float(lib.get(src, lib['w'] if src == 'b' else 0.0)))
            box.blockSignals(False)
        if update:
            self._eh_update()

    # ------------------------------------------------------------------ widok
    def enchole_hover(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        mesh = None
        what = self.eh['picking']
        try:
            if what == 'wall' and body is not None and (body.meta or {}).get('enclosure'):
                face, _n = self.view.face_at(body, hit)
                mesh = kernel.display_mesh(face) if face is not None and kernel.is_planar_face(face) else None
            elif what == 'element' and body is not None and body.kind == 'solid' and not (body.meta or {}).get('enclosure'):
                if self.eh_whole.isChecked():
                    mesh = body.mesh
                else:
                    face, _n = self.view.face_at(body, hit, curved=True)
                    mesh = kernel.display_mesh(face) if face is not None else None
            elif what == 'sketch':
                sid = self.view.pick_profile(x, y)
                sk = self.document.get(sid) if sid else None
                mesh = sk.mesh if sk is not None and sk.kind == 'sketch' else None
        except Exception:
            mesh = None
        self.view.set_hover_mesh(mesh)

    def enchole_click(self, x, y, shift=False):
        what = self.eh['picking']
        if what == 'sketch':
            sid = self.view.pick_profile(x, y)
            sk = self.document.get(sid) if sid else None
            if sk is None or sk.kind != 'sketch':
                self.toast('Kliknij zamknięty szkic.')
                return
            self.eh['sketch'] = sk.id
            self.eh['picking'] = 'element'
            self._eh_update()
            return
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij bryłę.')
            return
        if what == 'wall' or (body.meta or {}).get('enclosure'):
            if not (body.meta or {}).get('enclosure'):
                self.toast('Kliknij ściankę obudowy z Generatora obudów.')
                return
            try:
                face, normal = self.view.face_at(body, hit)
            except kernel.CadError as exc:
                self.toast(str(exc))
                return
            if face is None or not kernel.is_planar_face(face):
                self.toast('Otwór powstaje w płaskiej ściance - kliknij płaską ścianę obudowy.')
                return
            n = np.asarray(face.normalAt(face.Center()).toTuple(), float)
            self.eh['target'] = dict(id=body.id, point=[float(c) for c in hit[2]], normal=[float(c) for c in n])
            self.eh['picking'] = 'element'
            self._eh_update()
            return
        if self.eh_whole.isChecked():
            self.eh.update(whole=body.id, faces=[])
        else:
            face, _n = self.view.face_at(body, hit, curved=True)
            if face is None:
                return
            ref = (body.id, [float(c) for c in face.Center().toTuple()])
            self.eh['whole'] = None
            self.eh['faces'] = ([*self.eh['faces'], ref] if shift else [ref])
        if self.eh.get('target') is None:
            self._eh_propose()
        self._eh_update()

    # ------------------------------------------------------------------ dane
    def _eh_faces(self, bodies=None):
        return eh_faces(bodies or self.document.bodies, self.eh.get('whole'), self.eh.get('faces'))

    def _eh_propose(self):
        """Ścianka proponowana: najbliższa płaska ściana obudowy przed środkiem elementu (do zmiany kliknięciem)."""
        faces = self._eh_faces()
        if not faces:
            return
        import cadquery as cq
        c = np.mean([cq.Face(f).Center().toTuple() for f in faces], axis=0)
        prop = eh.propose_wall(enclosure_bodies(self.document.bodies), c)
        if prop is None:
            self.toast('Nie ma ścianki obudowy przed elementem - wskaż ją ręcznie.')
            return
        self.eh['target'] = dict(id=prop[0], point=[float(x) for x in prop[1]], normal=[float(x) for x in prop[2]], proposed=True)

    def eh_params(self):
        f = {k: b.value() for k, (_l, b) in self.eh_f.items()}
        return dict(mode=self.eh_mode.currentData(), library=self.eh_lib.currentData(),
                    lib=dict(w=f['lw'], h=f['lh'], b=f['lb'], r=f['lr']), radius=f['radius'],
                    clear=dict(l=f['cl'], r=f['cr'], b=f['cb'], t=f['ct']), du=f['du'], dv=f['dv'], angle=f['angle'],
                    cut=self.eh_cut.currentData(), depth=f['depth'], step=f['step'], step_depth=f['step_depth'], plug=f['plug'],
                    plug_depth=f['plug_depth'], finger=f['finger'], finger_dv=f['finger_dv'], cable=f['cable'])

    def eh_recipe(self):
        t = self.eh.get('target')
        if t is None:
            return None
        return dict(type='enc_hole', target=t['id'], point=t['point'], normal=t['normal'], direction=self.eh_dir.currentData(),
                    whole=self.eh.get('whole'), faces=[[i, p] for i, p in self.eh.get('faces') or []], sketch=self.eh.get('sketch'),
                    params=self.eh_params())

    def _eh_update(self):
        if not hasattr(self, 'eh_mode') or self.mode != 'enchole':
            return
        mode = self.eh_mode.currentData()
        cut = self.eh_cut.currentData()
        show = {'lw': mode == 'library', 'lh': mode == 'library', 'lr': mode == 'library',
                'lb': mode == 'library' and eh.LIBRARY[self.eh_lib.currentData()][1]['shape'] == 'trap', 'radius': mode == 'rrect',
                'depth': cut in ('recess', 'undercut'), 'step': cut == 'stepped', 'step_depth': cut == 'stepped',
                'plug_depth': self.eh_f['plug'][1].value() > 0 or self.eh_f['finger'][1].value() > 0,
                'finger_dv': self.eh_f['finger'][1].value() > 0}
        for key, (label, box) in self.eh_f.items():
            vis = show.get(key, True)
            label.setVisible(vis)
            box.setVisible(vis)
        self.eh_lib.setVisible(mode == 'library')
        self.eh_sketch_btn.setVisible(mode == 'sketch')
        sk = self.document.get(self.eh.get('sketch')) if self.eh.get('sketch') else None
        self.eh_sketch_btn.setText(f'Szkic: {sk.name} (wskaż inny)' if sk else 'Wskaż szkic z konturem')
        whole = self.document.get(self.eh.get('whole')) if self.eh.get('whole') else None
        nf = len(self.eh.get('faces') or [])
        self.eh_step1.set_state('done' if (whole or nf or mode in ('library', 'sketch')) else 'active',
                                whole.name if whole else (f'{nf} ściana(y)' if nf else ('opcjonalnie' if mode in ('library', 'sketch') else 'kliknij element')))
        t = self.eh.get('target')
        tb = self.document.get(t['id']) if t else None
        self.eh_step2.set_state('done' if tb else 'active', (tb.name + (' (propozycja)' if t.get('proposed') else '')) if tb else 'wskaż ściankę')
        self.eh_step3.set_state('active', eh.MODE_LABELS[mode].lower())
        self.eh_step4.set_state('active', eh.CUT_LABELS[cut].lower())
        self.view.tints = {i: (.30, .55, .95, 1) for i in {*(x[0] for x in self.eh.get('faces') or []), *([self.eh['whole']] if self.eh.get('whole') else [])}}
        self.eh_apply.setEnabled(False)
        recipe = self.eh_recipe()
        if recipe is None:
            self.view.set_preview_mesh(None)
            self.eh_status.setText('Kliknij element, a potem ściankę obudowy (albo wybierz profil z biblioteki i wskaż ściankę).')
            self.refresh()
            return
        bodies = list(self.document.bodies)
        sig = repr(recipe)
        self._eh_sig = sig
        self.eh_status.setText('Liczenie otworu…')

        def compute():
            shape, tool, info = build(bodies, recipe)
            return dict(tool=kernel.display_mesh(eh._cq_shape(tool)), info=info)

        def show(value, error):
            if self.mode != 'enchole' or getattr(self, '_eh_sig', None) != sig:
                return                               # nieaktualny wynik
            if error or value is None:
                self.view.set_preview_mesh(None)
                self.eh_status.setText(str(error) if error else 'Nie udało się policzyć otworu.')
                self.eh_apply.setEnabled(False)
                return
            info = value['info']
            self.view.set_preview_mesh(value['tool'], color=TOOL_FILL, line_color=TOOL_LINE, width=2, on_top=True)
            self.eh_status.setText(f'Pole otworu {info["area"]:.2f} mm², ścianka {info["thickness"]:.2f} mm, usunięte {info["removed"]:.2f} mm³. '
                                   'Enter albo Zastosuj wycina otwór (element zostaje bez zmian).')
            self.eh_apply.setEnabled(True)
        self.run_preview('enchole', compute, show)
        self.refresh()

    def _step_fill_enc_hole(self, recipe):
        """Edycja kroku otworu: element, ścianka i wszystkie parametry z przepisu."""
        p = dict(eh.DEFAULTS, **recipe['params'])
        self.eh.update(target=dict(id=recipe['target'], point=recipe['point'], normal=recipe['normal']), whole=recipe.get('whole'),
                       faces=[tuple(f) for f in recipe.get('faces') or []], sketch=recipe.get('sketch'), picking='element')
        widgets = [self.eh_mode, self.eh_lib, self.eh_cut, self.eh_dir, self.eh_whole, *[b for _l, b in self.eh_f.values()]]
        for w_ in widgets:
            w_.blockSignals(True)
        self.eh_whole.setChecked(bool(recipe.get('whole')))
        self.eh_mode.setCurrentIndex(self.eh_mode.findData(p['mode']))
        self.eh_lib.setCurrentIndex(max(0, self.eh_lib.findData(p.get('library'))))
        self.eh_cut.setCurrentIndex(self.eh_cut.findData(p['cut']))
        self.eh_dir.setCurrentIndex(max(0, self.eh_dir.findData(recipe.get('direction', 'normal'))))
        lib = dict(eh.LIBRARY.get(p.get('library'), eh.LIBRARY['usb_c'])[1], **(p.get('lib') or {}))
        c = dict(eh.DEFAULTS['clear'], **(p.get('clear') or {}))
        vals = dict(lw=lib['w'], lh=lib['h'], lb=lib.get('b', lib['w']), lr=lib.get('r', 0.0), radius=p['radius'], cl=c['l'], cr=c['r'], cb=c['b'],
                    ct=c['t'], du=p['du'], dv=p['dv'], angle=p['angle'], depth=p['depth'], step=p['step'], step_depth=p['step_depth'],
                    plug=p['plug'], plug_depth=p['plug_depth'], finger=p['finger'], finger_dv=p.get('finger_dv', 0.0), cable=p.get('cable', 0.0))
        for k, (_l, box) in self.eh_f.items():
            box.setValue(float(vals.get(k, box.value())))
        for w_ in widgets:
            w_.blockSignals(False)
        self._eh_update()

    # ------------------------------------------------------------------ zapis
    def apply_enchole(self):
        if self.busy or self.mode != 'enchole' or not self.eh_apply.isEnabled():
            return
        recipe = self.eh_recipe()
        if recipe is None:
            return
        editing = (getattr(self, '_step_edit', None) or {}).get('recipe') or {}
        recipe['id'] = editing.get('id') if editing.get('type') == recipe['type'] and editing.get('id') else uuid.uuid4().hex
        recipe['seq'] = editing.get('seq') if editing.get('type') == recipe['type'] and 'seq' in editing else len(self.document.states())
        existing = list(self.document.bodies)

        def build_step():
            return run(existing, recipe)

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Otwór na element'
            self.document.pending_icon = 'enchole'
            self.document.commit(bodies)

        def after():
            self.view.set_preview_mesh(None)
            self.eh.update(faces=[], whole=None, sketch=None, picking='element')
            self._eh_update()                      # narzędzie zostaje otwarte - kolejny otwór (każdy to osobna operacja)

        self.view.set_preview_mesh(None)
        self.run_operation('Otwór na element', build_step, apply, after=after)


# ---------------------------------------------------------------------------------------------- przeliczanie (historia)
def eh_faces(bodies, whole, refs):
    """Ściany elementu: cała bryła albo ściany odnalezione po punktach (najbliższa ściana do zapisanego punktu)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    by_id = {b.id: b for b in bodies}
    if whole:
        b = by_id.get(whole)
        if b is None:
            raise kernel.CadError('Elementu wskazanego dla otworu już nie ma.')
        return [f.wrapped for f in b.shape.Faces()]
    out = []
    for bid, point in refs or []:
        b = by_id.get(bid)
        if b is None:
            raise kernel.CadError('Elementu wskazanego dla otworu już nie ma.')
        v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, point))).Vertex()
        best = None
        for f in b.shape.Faces():
            dist = BRepExtrema_DistShapeShape(v, f.wrapped)
            dist.Perform()
            if dist.IsDone() and (best is None or dist.Value() < best[0]):
                best = (dist.Value(), f.wrapped)
        if best is None or best[0] > 1e-3:
            raise kernel.CadError('Nie udało się odnaleźć ściany elementu - wskaż ją ponownie.')
        out.append(best[1])
    return out


def build(bodies, recipe):
    """Narzędzie i obudowa z otworem według przepisu (okno i przeliczanie historii)."""
    import cadquery as cq
    by_id = {b.id: b for b in bodies}
    target = by_id.get(recipe['target'])
    if target is None or target.kind != 'solid':
        raise kernel.CadError('Ścianki obudowy wskazanej dla otworu już nie ma.')
    p = dict(eh.DEFAULTS, **recipe['params'])
    faces = eh_faces(bodies, recipe.get('whole'), recipe.get('faces')) if (recipe.get('whole') or recipe.get('faces')) else []
    direction = None
    if recipe.get('direction') == 'element' and faces:
        biggest = max((cq.Face(f) for f in faces), key=lambda f: f.Area())
        direction = np.asarray(biggest.normalAt(biggest.Center()).toTuple(), float)
        if float(direction @ np.asarray(recipe['normal'], float)) < 0:
            direction = -direction
    point = np.asarray(recipe['point'], float)
    if faces:                                       # środek profilu na rzucie elementu
        c = np.mean([cq.Face(f).Center().toTuple() for f in faces], axis=0)
        n = np.asarray(recipe['normal'], float)
        point = c - float((c - point) @ n) * n
    frame = eh.wall_frame(point, recipe['normal'], (0, 0, 1.0), direction)
    sketch_faces = None
    if p['mode'] == 'sketch':
        sk = by_id.get(recipe.get('sketch'))
        if sk is None:
            raise kernel.CadError('Wskaż zamknięty szkic z konturem otworu.')
        sketch_faces = [f.wrapped for f in sk.shape.Faces()]
        if not sketch_faces:
            wires = [w for w in sk.shape.Wires() if w.IsClosed()]
            sketch_faces = [cq.Face.makeFromWires(w).wrapped for w in wires]
        if not sketch_faces:
            raise kernel.CadError('Szkic nie ma zamkniętego konturu.')
    region, _centre = eh.build_profile(p, frame, faces, sketch_faces)
    shape, tool, info = eh.cut(target.shape, region, frame, p)
    if float(p.get('cable', 0.0)) > 0:               # miejsce na przewód / wtyczkę na zewnątrz: nic nie może tam stać
        keep = eh._prism(eh.offset_region(region, max(float(p.get('plug', 0.0)), .0)), frame, 0.0, float(p['cable']))
        from .enclosure import _boolean, _volume
        for b in bodies:
            if b.id == target.id or b.kind != 'solid':
                continue
            if _volume(_boolean('common', keep, b.shape.wrapped, 'miejsce na przewód'))[0] > 1e-4:
                raise kernel.CadError(f'Miejsce na wtyczkę / przewód zajmuje „{b.name}”.')
    return shape, tool, info


def tool_only(bodies, recipe, target_shape):
    """Samo narzędzie tnące otworu (do kontroli) - z części obudowy sprzed wycięcia."""
    from dataclasses import replace
    fake = [replace(b, shape=target_shape) if b.id == recipe['target'] else b for b in bodies]
    _shape, tool, _info = build(fake, recipe)
    return tool


def run(bodies, recipe):
    """Krok historii 'enc_hole': otwór wycięty w części obudowy (jej parametry Generatora zostają w meta)."""
    from dataclasses import replace
    shape, _tool, info = build(bodies, recipe)
    out = []
    for b in bodies:
        if b.id == recipe['target']:
            meta = dict(b.meta or {})
            holes = [h for h in meta.get('enclosure_holes', []) if h.get('id') != recipe.get('id')]
            meta['enclosure_holes'] = [*holes, {k: recipe[k] for k in recipe if k != 'type'}]
            b = replace(b, shape=shape, meta=meta, mesh=None).prepared()
        out.append(b)
    return out
