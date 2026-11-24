"""Dopasowanie i Wyrównanie dla szkiców (zakładka Szkic, górny pasek) - odpowiedniki narzędzi z zakładki Edycja.

- 'sfit' Dopasowanie szkicu: zaznaczony szkic (albo kilka szkiców) przenosi się na wskazaną płaską ścianę bryły albo do
  wnętrza zamkniętego szkicu - środek szkicu trafia w środek ściany / szkicu, a płaszczyzna szkicu układa się na ścianie
  (szkic leży na niej i dalej da się go wyciągnąć). Obrót wokół normalnej co 90° albo dowolny kąt.
- 'salign' Wyrównanie szkicu: wskazana prosta linia szkicu (albo skrajny punkt okręgu / łuku) ustawia się na linii
  wzorcowej - krawędzi bryły leżącej w płaszczyźnie szkicu albo prostej linii innego szkicu. Linia nierównoległa najpierw
  obraca się (w płaszczyźnie szkicu) równolegle do wzorca, potem cały szkic przesuwa się prostopadle do wzorca.
Szkice z wymiarami (okrąg, prostokąt…) zachowują je - przesuwa się / obraca ich płaszczyzna. Zapis: zwykły krok historii
(„Dopasowanie szkicu” / „Wyrównanie szkicu”), Cofnij przywraca położenie."""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox

from . import dims
from . import kernel
from . import shell_ui as ui


def _label(text, name='label'):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def _unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def axis_rotation(axis, degrees):
    a = _unit(axis)
    t = np.radians(float(degrees))
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(t) * k + (1 - np.cos(t)) * (k @ k)


def placed_sketch(body, rotation, translation, meta_shape):
    """Szkic po sztywnym obrocie i przesunięciu. Ruch w jego własnej płaszczyźnie bez obrotu - przesuwają się punkty
    wymiarów (dims.moved); inaczej obraca się i przesuwa płaszczyzna szkicu, więc wymiary (punkty w układzie płaszczyzny)
    zostają ważne."""
    r = np.asarray(rotation, float)
    t = np.asarray(translation, float)
    frame = kernel.frame_of(body.plane)
    n = np.asarray(frame.normal, float)
    if np.allclose(r, np.eye(3), atol=1e-9) and abs(float(t @ n)) < 1e-9:
        return dims.moved(body, t, meta_shape)
    shape = kernel.transformed(body.shape, r, t)
    origin = r @ np.asarray(frame.origin, float) + t
    plane = kernel.Frame(tuple(float(c) for c in origin), tuple(float(c) for c in _unit(r @ np.asarray(frame.xdir, float))),
                         tuple(float(c) for c in _unit(r @ n)))
    return replace(body, shape=shape, plane=plane, mesh=kernel.display_mesh(shape))


def sketch_center(shapes):
    """Środek szkicu (szkiców): środek ciężkości zamkniętego obrysu, inaczej środek ramki."""
    if len(shapes) == 1:
        wires = shapes[0].Wires()
        if len(wires) == 1 and wires[0].IsClosed():
            try:
                import cadquery as cq
                return np.array(cq.Face.makeFromWires(wires[0]).Center().toTuple(), float)
            except Exception:
                pass
    box = kernel.bounds(kernel.compound(list(shapes)))
    return np.array(box.center.toTuple(), float)


class SketchPlace:
    # ------------------------------------------------------------------ panele
    def _build_sketch_place_panels(self):
        # --- dopasowanie szkicu ---
        self.sfit = dict(ids=[], target=None, stage='shapes')
        self.sfit_panel, lay = self._panel(300, 'Dopasowanie szkicu', 'x_sfit', 'Szkic → środek ściany / szkicu', plain=True)
        self.sfit_step1 = ui.StepRow(1, 'x_area', 'Szkice do przeniesienia', plain=True)
        self.sfit_step2 = ui.StepRow(2, 'x_wall', 'Ściana albo zamknięty szkic', plain=True)
        lay.addWidget(self.sfit_step1)
        lay.addWidget(self.sfit_step2)
        self.sfit_next = QPushButton('Dalej: wskaż cel')
        self.sfit_next.clicked.connect(lambda _=False: self._sfit_stage('target'))
        lay.addWidget(self.sfit_next)
        lay.addWidget(_label('Obrót wokół środka', 'label'))
        row = QHBoxLayout()
        row.setSpacing(6)
        left, right = QPushButton('↺ 90°'), QPushButton('↻ 90°')
        left.clicked.connect(lambda _=False: self._sfit_turn(90))
        right.clicked.connect(lambda _=False: self._sfit_turn(-90))
        self.sfit_angle = QDoubleSpinBox()
        self.sfit_angle.setRange(-360, 360)
        self.sfit_angle.setDecimals(1)
        self.sfit_angle.setSuffix('°')
        self.sfit_angle.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.sfit_angle.valueChanged.connect(lambda *_: self._sfit_preview())
        row.addWidget(left)
        row.addWidget(self.sfit_angle, 1)
        row.addWidget(right)
        lay.addLayout(row)
        self.sfit_status = _label('Klikaj szkice do przeniesienia.', 'status')
        lay.addWidget(self.sfit_status)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_sfit, lambda: self.set_mode(None))

        # --- wyrównanie szkicu ---
        self.salign = dict(source=None, target=None)
        self.salign_panel, lay = self._panel(300, 'Wyrównanie szkicu', 'x_salign', 'Linia szkicu → linia wzorcowa', plain=True)
        self.salign_step1 = ui.StepRow(1, 'x_salign', 'Linia albo punkt okręgu', plain=True)
        self.salign_step2 = ui.StepRow(2, 'x_salign', 'Krawędź albo linia wzorcowa', plain=True)
        lay.addWidget(self.salign_step1)
        lay.addWidget(self.salign_step2)
        self.salign_status = _label('Kliknij linię szkicu albo okrąg.', 'status')
        lay.addWidget(self.salign_status)
        lay.addWidget(_label('Skośna linia obraca się równolegle do wzorca.', 'hint'))
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_salign, lambda: self.set_mode(None))
        return (self.sfit_panel, self.salign_panel)

    def sketch_place_panels(self):
        return (self.sfit_panel, self.salign_panel)

    def _splace_begin(self, mode):
        """set_mode('sfit' / 'salign'): panel i stan narzędzia; zaznaczone szkice od razu trafiają do Dopasowania."""
        self.override = {}
        self.view.set_preview_mesh(None)
        if mode == 'sfit':
            chosen = [i for i in self.selected if self._splace_sketch_ok(self.document.get(i))]
            self.sfit = dict(ids=chosen, target=None, stage='target' if chosen else 'shapes')
            self.sfit_angle.blockSignals(True)
            self.sfit_angle.setValue(0)
            self.sfit_angle.blockSignals(False)
            self.sfit_panel.show()
            self._sfit_update()
            self.hint('Dopasowanie szkicu: zaznacz szkice, potem kliknij płaską ścianę bryły albo zamknięty szkic.')
        else:
            self.salign = dict(source=None, target=None)
            self.salign_panel.show()
            self._salign_update()
            self.hint('Wyrównanie szkicu: kliknij linię szkicu (albo okrąg), potem krawędź bryły albo linię innego szkicu.')
        self.view.setCursor(Qt.PointingHandCursor)

    @staticmethod
    def _splace_sketch_ok(body):
        return body is not None and body.kind == 'sketch' and body.visible and not (body.meta or {}).get('surface')

    def _splace_sketch_at(self, x, y):
        hit = self.view.nearest_edge(x, y, kinds=('sketch',))
        body = self.document.get(hit[0]) if hit else None
        return (body, hit[1]) if self._splace_sketch_ok(body) else (None, None)

    def splace_hover(self, x, y):
        if self.mode == 'sfit':
            if self.sfit['stage'] == 'shapes':
                body, _ = self._splace_sketch_at(x, y)
                self.view.set_hover_body(body.id if body is not None else None)
                return
            body, _ = self._splace_sketch_at(x, y)
            if body is not None and body.id not in self.sfit['ids'] and self._closed(body):
                self.view.set_hover_body(body.id)
                self._hover_key = None
                if self.sfit['target'] is None:
                    self.view.set_preview_mesh(None)
                return
            self.view.set_hover_body(None)
            if self.sfit['target'] is None:
                self._hover_face_only(x, y)
        else:
            if self.salign['source'] is None:
                body, edge = self._splace_sketch_at(x, y)
                self.view._set_hover_edge((body.id, edge) if body is not None else None)
                pt = self._salign_circle_point(body, edge, x, y) if body is not None else None
                self.view.set_marker(pt, label='skrajny punkt') if pt is not None else self.view.set_marker(None)
            elif self.salign['target'] is None:
                found = self._salign_target_at(x, y)
                self.view._set_hover_edge(found[0] if found else None)

    def splace_click(self, x, y, shift=False):
        if self.mode == 'sfit':
            self._sfit_click(x, y)
        else:
            self._salign_click(x, y)

    def splace_right(self, x, y):
        """Prawy klik na wybranym szkicu, ścianie albo linii odznacza go."""
        body, _ = self._splace_sketch_at(x, y)
        if self.mode == 'sfit':
            target = self.sfit['target']
            if body is not None and body.id in self.sfit['ids']:
                self.sfit['ids'].remove(body.id)
                if not self.sfit['ids']:
                    self.sfit['stage'] = 'shapes'
            elif target is not None and target['kind'] == 'sketch' and body is not None and body.id == target['id']:
                self.sfit['target'] = None
            elif target is not None and target['kind'] == 'face':
                hit = self.view.pick_face(x, y)
                if not hit or hit[0] != target['id']:
                    return False
                self.sfit['target'] = None              # ściana-cel odznaczona
            else:
                return False
            self.override = {}
            self._sfit_update()
            return True
        source, target = self.salign['source'], self.salign['target']
        if target is not None:
            found = self._salign_target_at(x, y)
            if found is not None and found[0][0] == target['id']:
                self.salign['target'] = None
                self.override = {}
                self._salign_update()
                return True
        if source is not None and body is not None and body.id in source['ids']:
            self.salign = dict(source=None, target=None)
            self.override = {}
            self._salign_update()
            return True
        return False

    def _splace_commit(self, changed, label):
        bodies = [changed.get(b.id, b) for b in self.document.bodies]
        ids = list(changed)

        def apply(result):
            self.document.pending_op = None
            self.document.pending_label = label
            self.document.commit(result)

        mode = self.mode

        def after():
            # okno zostaje otwarte: można od razu wybrać kolejne szkice (zamyka je Zamknij albo inne narzędzie)
            self.override = {}
            if self.mode != mode:
                return
            if mode == 'sfit':
                self.sfit = dict(ids=[], target=None, stage='shapes')
                self.sfit_angle.blockSignals(True)
                self.sfit_angle.setValue(0)
                self.sfit_angle.blockSignals(False)
                self._sfit_update()
            else:
                self.salign = dict(source=None, target=None)
                self._salign_update()
            self.toast(f'{label} - gotowe. Wybierz kolejne szkice albo Zamknij.', 2500)
        self.override = {}
        self.view.set_preview_mesh(None)
        self.run_operation(label, lambda: list(bodies), apply, after=after)

    # ------------------------------------------------------------------ dopasowanie
    @staticmethod
    def _closed(body):
        try:
            wires = body.shape.Wires()
            return bool(wires) and all(w.IsClosed() for w in wires)
        except Exception:
            return False

    def _sfit_stage(self, stage):
        if stage == 'target' and not self.sfit['ids']:
            self.toast('Najpierw kliknij szkic (albo kilka szkiców) do przeniesienia.')
            return
        self.sfit['stage'] = stage
        self._sfit_update()

    def _sfit_click(self, x, y):
        body, _ = self._splace_sketch_at(x, y)
        if self.sfit['stage'] == 'shapes':
            if body is None:
                self.toast('Kliknij szkic do przeniesienia.')
                return
            ids = self.sfit['ids']
            ids.remove(body.id) if body.id in ids else ids.append(body.id)
            self._sfit_update()
            return
        if body is not None and body.id in self.sfit['ids']:
            ids = self.sfit['ids']                 # klik w przenoszony szkic: odznacza go
            ids.remove(body.id)
            if not ids:
                self.sfit['stage'] = 'shapes'
            self._sfit_update()
            return
        if body is not None and self._closed(body):
            frame = kernel.frame_of(kernel.actual_frame(body.shape, body.plane))
            self.sfit['target'] = dict(kind='sketch', id=body.id, name=body.name, center=sketch_center([body.shape]),
                                       normal=_unit(frame.normal))
            self._sfit_update()
            return
        hit = self.view.pick_face(x, y)
        solid = self.document.get(hit[0]) if hit else None
        if solid is None or solid.kind != 'solid':
            self.toast('Kliknij płaską ścianę bryły albo zamknięty szkic.')
            return
        try:
            face, normal = self.view.face_at(solid, hit)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        if face is None or face.geomType() != 'PLANE':
            self.toast('Ściana musi być płaska.')
            return
        self.sfit['target'] = dict(kind='face', id=solid.id, name=solid.name, center=np.array(face.Center().toTuple(), float),
                                   normal=_unit(normal))
        self.view.set_preview_mesh(None)
        self._hover_key = None
        self._sfit_update()

    def _sfit_turn(self, degrees):
        value = self.sfit_angle.value() + degrees
        value = (value + 180) % 360 - 180
        self.sfit_angle.setValue(value)

    def _sfit_result(self):
        bodies = [self.document.get(i) for i in self.sfit['ids']]
        bodies = [b for b in bodies if b is not None]
        target = self.sfit['target']
        if not bodies or target is None:
            raise kernel.CadError('Wybierz szkice i cel.')
        frame = kernel.frame_of(kernel.actual_frame(bodies[0].shape, bodies[0].plane))
        n0 = _unit(frame.normal)
        c0 = sketch_center([b.shape for b in bodies])
        nt, ct = target['normal'], target['center']
        rot = axis_rotation(nt, self.sfit_angle.value()) @ kernel.rotation_between(n0, nt)
        shift = ct - rot @ c0
        return {b.id: placed_sketch(b, rot, shift, self._meta_shape) for b in bodies}

    def _sfit_update(self):
        ids = [i for i in self.sfit['ids'] if self.document.get(i) is not None]
        self.sfit['ids'] = ids
        stage, target = self.sfit['stage'], self.sfit['target']
        self.sfit_step1.set_state('done' if ids and stage == 'target' else 'active', f'{len(ids)} szkic(e)' if ids else 'kliknij szkice')
        self.sfit_step2.set_state('done' if target else ('active' if stage == 'target' else 'pending'),
                                  (('ściana: ' if target['kind'] == 'face' else 'szkic: ') + target['name']) if target else '')
        self.sfit_next.setVisible(stage == 'shapes')
        self.sfit_status.setText('Klikaj szkice, potem „Dalej”.' if stage == 'shapes' else
                                 ('Kliknij ścianę bryły albo zamknięty szkic.' if target is None else 'Enter przenosi szkic.'))
        self.selected = list(ids)
        self._sfit_preview()

    def _sfit_preview(self):
        if self.mode != 'sfit':
            return
        try:
            self.override = self._sfit_result() if self.sfit['target'] is not None else {}
        except Exception:
            self.override = {}
        self.refresh()

    def apply_sfit(self):
        if self.busy or self.mode != 'sfit':
            return
        try:
            changed = self._sfit_result()
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        self._splace_commit(changed, 'Dopasowanie szkicu')

    # ------------------------------------------------------------------ wyrównanie
    def _salign_circle_point(self, body, edge, x, y):
        """Okrąg / łuk: jeden z czterech skrajnych punktów (w osiach płaszczyzny szkicu) najbliższy kursorowi."""
        e = body.shape.Edges()[edge]
        if e.geomType() != 'CIRCLE':
            return None
        frame = kernel.frame_of(kernel.actual_frame(body.shape, body.plane))
        c = np.array(e.arcCenter().toTuple(), float)
        r = float(e.radius())
        u = np.asarray(frame.xdir, float)
        v = np.asarray(frame.ydir, float)
        pts = [c + u * r, c - u * r, c + v * r, c - v * r]
        if not e.IsClosed():            # łuk: tylko skrajne punkty, które na nim leżą, i jego końce
            pts = [p for p in pts if e.distanceTo(__import__('cadquery').Vector(*p)) < 1e-6] + \
                  [np.array(e.startPoint().toTuple(), float), np.array(e.endPoint().toTuple(), float)]
        xy, _, w = self.view.project_points(np.asarray(pts, float))
        dist = np.linalg.norm(xy - [x, y], axis=1)
        dist[w <= 0] = np.inf
        return np.asarray(pts[int(np.argmin(dist))], float)

    def _salign_target_at(self, x, y):
        """Linia wzorcowa pod kursorem: prosta linia innego szkicu albo prosta krawędź bryły w płaszczyźnie szkicu.
        ((id, krawędź), punkt, kierunek) albo None."""
        source = self.salign['source']
        moving = set(source['ids']) if source else set()
        hit = self.view.nearest_edge(x, y, kinds=('sketch',))
        if hit is not None and hit[0] in moving:
            hit = None
        if hit is None:
            hit = self.view.nearest_edge(x, y, solids_only=True)
        if hit is None:
            return None
        body = self.document.get(hit[0])
        if body is None or body.id in moving:
            return None
        e = body.shape.Edges()[hit[1]]
        if e.geomType() != 'LINE':
            return None
        a, b = np.array(e.startPoint().toTuple(), float), np.array(e.endPoint().toTuple(), float)
        if source is not None:
            n, o = source['normal'], source['origin']
            if abs(float((a - o) @ n)) > 1e-3 or abs(float((b - o) @ n)) > 1e-3:
                return None                          # krawędź nie leży w płaszczyźnie szkicu
        return hit, a, _unit(b - a)

    def _salign_click(self, x, y):
        if self.salign['source'] is None or self.salign['target'] is not None:
            body, edge = self._splace_sketch_at(x, y)
            if body is None:
                self.toast('Kliknij prostą linię szkicu albo okrąg.')
                return
            e = body.shape.Edges()[edge]
            frame = kernel.frame_of(kernel.actual_frame(body.shape, body.plane))
            ids = [i for i in self.selected if self._splace_sketch_ok(self.document.get(i))] if body.id in self.selected else [body.id]
            base = dict(ids=ids, name=body.name, normal=_unit(frame.normal), origin=np.asarray(frame.origin, float))
            if e.geomType() == 'LINE':
                self.salign = dict(source=dict(base, kind='line', a=np.array(e.startPoint().toTuple(), float),
                                               b=np.array(e.endPoint().toTuple(), float)), target=None)
            else:
                point = self._salign_circle_point(body, edge, x, y)
                if point is None:
                    self.toast('Kliknij prostą linię albo okrąg / łuk (przy skrajnym punkcie).')
                    return
                self.salign = dict(source=dict(base, kind='point', p=point), target=None)
            self.view.set_marker(None)
            self.view._set_hover_edge(None)
            self._salign_update()
            return
        found = self._salign_target_at(x, y)
        if found is None:
            self.toast('Kliknij prostą krawędź bryły leżącą w płaszczyźnie szkicu albo prostą linię innego szkicu.')
            return
        (bid, edge), q, w = found
        body = self.document.get(bid)
        self.salign['target'] = dict(id=bid, name=body.name, kind=body.kind, q=q, w=w)
        self.view._set_hover_edge(None)
        self._salign_update()

    def _salign_result(self):
        source, target = self.salign['source'], self.salign['target']
        if source is None or target is None:
            raise kernel.CadError('Wskaż linię szkicu i linię wzorcową.')
        n = source['normal']
        q, w = target['q'], target['w']
        w = _unit(w - (w @ n) * n)
        rot = np.eye(3)
        if source['kind'] == 'line':
            a, b = source['a'], source['b']
            u = _unit(b - a)
            angle = np.degrees(np.arctan2(float(np.cross(u, w) @ n), float(u @ w)))
            if angle > 90:
                angle -= 180
            elif angle < -90:
                angle += 180                     # obrót o mniejszy kąt: linia może być skierowana w drugą stronę
            pivot = (a + b) / 2
            rot = axis_rotation(n, angle) if abs(angle) > 1e-9 else np.eye(3)
            point = pivot
            shift0 = pivot - rot @ pivot         # obrót wokół środka linii
        else:
            point = source['p']
            shift0 = np.zeros(3)
        rel = q - point
        perp = rel - (rel @ w) * w
        perp = perp - (perp @ n) * n
        shift = shift0 + perp
        out = {}
        for i in source['ids']:
            body = self.document.get(i)
            if body is not None:
                out[i] = placed_sketch(body, rot, shift, self._meta_shape)
        if not out:
            raise kernel.CadError('Szkicu już nie ma.')
        return out

    def _salign_update(self):
        source, target = self.salign['source'], self.salign['target']
        self.salign_step1.set_state('done' if source else 'active',
                                    (('linia · ' if source['kind'] == 'line' else 'skrajny punkt · ') + source['name']) if source else 'kliknij linię')
        self.salign_step2.set_state('done' if target else ('active' if source else 'pending'),
                                    (('krawędź · ' if target['kind'] == 'solid' else 'linia · ') + target['name']) if target else '')
        self.salign_status.setText('Kliknij linię szkicu albo okrąg.' if source is None else
                                   ('Kliknij krawędź bryły albo linię szkicu.' if target is None else 'Enter wyrównuje szkic.'))
        self.selected = list(source['ids']) if source else []
        try:
            self.override = self._salign_result() if target is not None else {}
        except Exception:
            self.override = {}
        self.refresh()

    def apply_salign(self):
        if self.busy or self.mode != 'salign':
            return
        try:
            changed = self._salign_result()
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        self._splace_commit(changed, 'Wyrównanie szkicu')
