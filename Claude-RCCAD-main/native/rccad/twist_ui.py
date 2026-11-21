"""TWIST – Skręcanie brył (zakładka Edycja).

Mixin okna Studio.
Etap 1: przycisk, panel parametrów, wybór bryły istniejącym zaznaczeniem, kąt (domyślnie 90°), Enter / Esc.
Etap 2: oś skręcenia widoczna w 3D (linia ze strzałką kierunku przez bryłę) - globalna X / Y / Z przez środek bryły,
lokalna oś bryły (główne osie bezwładności), przez dwa punkty, wzdłuż prostej krawędzi albo oś powierzchni walcowej;
odwrócenie kierunku; manipulator obrotowy (pierścień z istniejącego systemu uchwytów widoku) przy końcu bryły - łuk
pokazuje kierunek i wartość skręcenia, przeciąganie zmienia kąt.

Etap 4: szybki podgląd skręcenia na KOPII siatki wyświetlania (rccad/twist_preview.py + silnik rccad/twist_math.py).
Oryginał jest na czas podglądu tylko ukryty w widoku (istniejący mechanizm podmiany override), bryła B-Rep i jej siatka
w projekcie się nie zmieniają. Kąt z pola i z pierścienia odświeża podgląd (zmiany zbierane do jednej klatki).
Anuluj / Esc / zmiana narzędzia przywracają oryginalny widok.

Etap 5: Zastosuj skręca bryłę B-Rep (rccad/twist_occ.py: bryły o stałym przekroju wzdłuż osi) - krok historii 'twist'.
Siatka podglądu nigdy nie trafia do projektu. Geometria osi: rccad/twist.py."""
from __future__ import annotations

import math

import numpy as np
from dataclasses import replace

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QWidget

from . import history as hist
from . import kernel
from . import shell_ui as ui
from . import twist as tw
from . import twist_math as tm
from . import twist_preview as tp

TWIST_AXES = (('X', 'X', 'tw_x'), ('Y', 'Y', 'tw_y'), ('Z', 'Z', 'tw_z'))
TWIST_KINDS = (('Globalna', 'global', 'tw_global'), ('Lokalna', 'local', 'tw_local'), ('2 punkty', 'points', 'tw_points'),
               ('Krawędź', 'edge', 'tw_edge'), ('Walec', 'cyl', 'tw_cyl'))
KIND_HINTS = {'global': 'Oś X / Y / Z układu globalnego przez środek bryły.',
              'local': 'Oś własna bryły (główne osie bezwładności przez środek masy) - obraca się razem z bryłą.',
              'points': 'Kliknij dwa punkty osi (narożnik, punkt krawędzi albo powierzchni).',
              'edge': 'Kliknij prostą krawędź - oś biegnie wzdłuż niej.',
              'cyl': 'Kliknij powierzchnię walcową (otwór, wałek) - oś walca.'}
DISTRIBUTION_ITEMS = (('Liniowy', 'linear', 'tw_lin'), ('Płynny', 'smoothstep', 'tw_smooth'), ('Progresywny', 'progressive', 'tw_prog'))
ANCHOR_ITEMS = (('Początek', 'start', 'tw_astart'), ('Środek', 'center', 'tw_acenter'), ('Koniec', 'end', 'tw_aend'))
DEFAULT_TOLERANCE = 0.01
RING_COLOR = (.94, .6, .13, 1)
PREVIEW_COLOR, PREVIEW_LINE = (.3, .75, .5, .8), (.05, .4, .2, 1)
AXIS_LINE = (.94, .42, .05, 1)


class TwistTools:
    def _build_twist_panel(self):
        from .studio import _label, _spin
        self.twist_panel, lay = self._panel(330, 'TWIST – Skręcanie', 'x_twist', 'Skręcenie bryły wokół osi', plain=True, scroll=True)
        self.tx_step = ui.StepRow(1, 'x_object', 'Bryła', plain=True)
        lay.addWidget(self.tx_step)
        self.tx_angle = _spin(90.0, -3600.0, 3600.0, 1, 5)
        self.tx_angle.setSuffix('°')
        self.tx_angle.setToolTip('Kąt skręcenia w stopniach: o tyle obróci się jeden koniec bryły względem drugiego (ujemny - w drugą stronę). '
                                 'Pierścień przy bryle można też przeciągać.')
        self._field(lay, 'Kąt skręcenia (°)', self.tx_angle)
        self.tx_step2 = ui.StepRow(2, 'tw_global', 'Oś skręcenia', plain=True)
        lay.addWidget(self.tx_step2)
        self.tx_kind = ui.Segmented(list(TWIST_KINDS), 24)
        for button, (_, key, _) in zip(self.tx_kind._buttons, TWIST_KINDS):
            button.setToolTip(KIND_HINTS[key])
        lay.addWidget(self.tx_kind)
        self.tx_axis = ui.Segmented(list(TWIST_AXES), 30)
        for button, axis in zip(self.tx_axis._buttons, 'XYZ'):
            button.setToolTip(f'Bryła skręca się wokół osi {axis} (przechodzącej przez jej środek).')
        self.tx_axis.setCurrentIndex(2)
        self.tx_axis_label = _label('Oś')
        lay.addWidget(self.tx_axis_label)
        lay.addWidget(self.tx_axis)
        self.tx_reverse = QCheckBox('Odwróć kierunek osi')
        self.tx_reverse.setToolTip('Zmienia zwrot osi - skręcenie o ten sam kąt idzie w drugą stronę.')
        lay.addWidget(self.tx_reverse)
        self.tx_info = _label('', 'help')
        self.tx_info.setWordWrap(True)
        lay.addWidget(self.tx_info)
        # etap 8: pozostałe parametry kroku - zakres, rozkład, zakotwiczenie, tolerancja (zapisywane w historii)
        self.tx_step3 = ui.StepRow(3, 'tw_lin', 'Zakres i rozkład', plain=True)
        lay.addWidget(self.tx_step3)
        self.tx_from = _spin(0.0, 0.0, 99.9, 1, 5)
        self.tx_to = _spin(100.0, .1, 100.0, 1, 5)
        for spin in (self.tx_from, self.tx_to):
            spin.setSuffix(' %')
        self.tx_from.setToolTip('Początek skręcanej części bryły - w procentach długości wzdłuż osi (0 % - od początku).')
        self.tx_to.setToolTip('Koniec skręcanej części bryły - w procentach długości (100 % - do końca). Poza zakresem bryła się nie skręca.')
        span = QWidget()
        row = QHBoxLayout(span)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.tx_from)
        row.addWidget(QLabel('–'))
        row.addWidget(self.tx_to)
        self._field(lay, 'Zakres skręcenia (% długości)', span)
        self.tx_dist = ui.Segmented(list(DISTRIBUTION_ITEMS), 24)
        for button, tip in zip(self.tx_dist._buttons, ('Kąt narasta równomiernie na całym zakresie.',
                                                        'Łagodny początek i koniec skręcenia (Smoothstep).',
                                                        'Skręcenie narasta coraz szybciej ku końcowi zakresu.')):
            button.setToolTip(tip)
        self._field(lay, 'Rozkład skręcenia', self.tx_dist)
        self.tx_anchor = ui.Segmented(list(ANCHOR_ITEMS), 24)
        for button, tip in zip(self.tx_anchor._buttons, ('Przekrój na początku osi zostaje w miejscu (domyślnie).',
                                                          'Przekrój w połowie długości zostaje w miejscu - końce obracają się w przeciwne strony.',
                                                          'Przekrój na końcu osi zostaje w miejscu.')):
            button.setToolTip(tip)
        self._field(lay, 'Zakotwiczenie (co stoi w miejscu)', self.tx_anchor)
        self.tx_tol = _spin(DEFAULT_TOLERANCE, .001, 1.0, 3, .005)
        self.tx_tol.setSuffix(' mm')
        self.tx_tol.setToolTip('Największa dopuszczalna odchyłka skręconej powierzchni od dokładnego skręcenia (kontrola wyniku).')
        self._field(lay, 'Tolerancja (mm)', self.tx_tol)
        self.tx_status = _label('', 'status')
        self.tx_status.setWordWrap(True)
        lay.addWidget(self.tx_status)
        self.tx_apply, cancel = self._buttons(self.twist_panel.footer, 'Zastosuj', 'Anuluj', self.apply_twist, self.cancel_twist)
        self.tx_apply.setToolTip('Zatwierdza skręcenie (Enter).')
        cancel.setToolTip('Zamyka narzędzie bez zmian (Esc).')
        self.tx_id = None
        self.tx_points = []           # punkty wskazane w trybie „2 punkty”
        self.tx_line = None           # oś wskazana krawędzią / walcem: dict(p, d, label)
        self._tx_cache = {}
        self._tx_rebuild = None       # przebudowa bryły ze źródła zapisanego w meta['twist'] (np. wstawionej z biblioteki)
        self._tx_timer = QTimer(self)               # zmiany kąta (pole, przeciąganie pierścienia) - jeden podgląd na klatkę
        self._tx_timer.setSingleShot(True)
        self._tx_timer.setInterval(0)
        self._tx_timer.timeout.connect(self._tx_preview)
        self.tx_angle.valueChanged.connect(lambda *_: self._tx_angle_changed())
        self.tx_axis.currentIndexChanged.connect(lambda *_: self._tx_refresh())
        self.tx_reverse.toggled.connect(lambda *_: self._tx_refresh())
        self.tx_kind.currentIndexChanged.connect(lambda *_: self._tx_kind_changed())
        for spin in (self.tx_from, self.tx_to, self.tx_tol):
            spin.valueChanged.connect(lambda *_: self._tx_refresh())
        for seg in (self.tx_dist, self.tx_anchor):
            seg.currentIndexChanged.connect(lambda *_: self._tx_refresh())

    # ---------- wejście / wybór bryły ----------
    def _twist_enter(self):
        self.twist_panel.show()
        self.view.setCursor(Qt.PointingHandCursor)
        for widget, value in ((self.tx_angle, 90.0), (self.tx_from, 0.0), (self.tx_to, 100.0), (self.tx_tol, DEFAULT_TOLERANCE)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        for widget in (self.tx_axis, self.tx_kind, self.tx_reverse, self.tx_dist, self.tx_anchor):
            widget.blockSignals(True)
        self.tx_axis.setCurrentIndex(2)
        self.tx_kind.setCurrentIndex(0)
        self.tx_reverse.setChecked(False)
        self.tx_dist.setCurrentIndex(0)
        self.tx_anchor.setCurrentIndex(0)
        for widget in (self.tx_axis, self.tx_kind, self.tx_reverse, self.tx_dist, self.tx_anchor):
            widget.blockSignals(False)
        self.tx_points, self.tx_line, self._tx_cache, self._tx_rebuild = [], None, {}, None
        self._tx_kind_widgets()
        solids = [i for i in self.selected if self._tx_solid(i) is not None]
        picked = solids[0] if solids else None
        self._tx_set(picked)
        self.hint('TWIST: kliknij bryłę, ustaw kąt i oś; pierścień przy bryle obraca kąt. Enter zatwierdza, Esc anuluje.')
        if len(solids) > 1:
            # zaznaczone kilka brył (np. całe złożenie z pliku STEP) - skręcana jest tylko jedna, reszta zostaje bez zmian
            self.toast(f'Zaznaczono {len(solids)} brył - TWIST skręci tylko jedną: „{self.document.get(picked).name}”. '
                       'Inną wybierzesz kliknięciem; pozostałe zostają bez zmian.', 6000)

    def _tx_solid(self, bid):
        body = self.document.get(bid) if bid else None
        return body if body is not None and body.kind == 'solid' else None

    def _tx_picking_axis(self):
        """Kliknięcia wskazują oś (2 punkty / krawędź / walec), a nie bryłę."""
        return self.tx_kind.currentData() in ('points', 'edge', 'cyl') and self._tx_solid(self.tx_id) is not None

    def pick_twist(self, x, y):
        if self._tx_picking_axis():
            self._tx_pick_axis(x, y)
            return
        body = self._tx_solid(self.view.pick_body(x, y))
        if body is None:
            self.toast('Kliknij bryłę do skręcenia.')
            return
        self._tx_set(body.id)

    def twist_hover(self, x, y):
        if not self._tx_picking_axis():
            self._hover_shell_solid(x, y)
            return
        kind = self.tx_kind.currentData()
        if kind == 'points':
            ref = self._tx_point_at(x, y)
            self.view.hover_vertex = ref
            self.view.overlay.update()
        elif kind == 'edge':
            hit = self.view.nearest_edge(x, y)
            body = self.document.get(hit[0]) if hit else None
            ok = body is not None and body.shape.Edges()[hit[1]].geomType() == 'LINE'
            self.view._set_hover_edge((hit[0], hit[1]) if ok else None)
        else:
            face = self._tx_face_at(x, y)
            ok = face is not None and face.geomType() == 'CYLINDER'
            self.view.set_hover_mesh(kernel.display_mesh(face) if ok else None)

    def _tx_set(self, bid):
        if self._tx_rebuild is not None and self._tx_rebuild['id'] != bid:
            self._tx_rebuild = None
        self.tx_id = bid
        self.selected = [bid] if bid else []
        self.refresh()
        body = self._tx_solid(bid)
        self.tx_step.set_state('done' if body else 'active', body.name if body else '')
        self._tx_refresh()

    # ---------- wskazywanie osi ----------
    def _tx_point_at(self, x, y):
        vertex = self.view.nearest_vertex(x, y, solids_only=False)
        if vertex is not None:
            return np.asarray(vertex[1], float)
        hit = self.view.pick_face(x, y)
        return np.asarray(hit[2], float) if hit else None

    def _tx_face_at(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            return None
        try:
            face, _ = self.view.face_at(body, hit, curved=True)
        except Exception:
            return None
        return face

    def _tx_pick_axis(self, x, y):
        kind = self.tx_kind.currentData()
        try:
            if kind == 'points':
                point = self._tx_point_at(x, y)
                if point is None:
                    raise kernel.CadError('Kliknij narożnik, krawędź albo powierzchnię.')
                if len(self.tx_points) >= 2:
                    self.tx_points = []
                if self.tx_points and float(np.linalg.norm(point - self.tx_points[0])) < 1e-6:
                    raise kernel.CadError('Drugi punkt osi musi być w innym miejscu.')
                self.tx_points.append(point)
            elif kind == 'edge':
                hit = self.view.nearest_edge(x, y)
                body = self.document.get(hit[0]) if hit else None
                if body is None:
                    raise kernel.CadError('Kliknij prostą krawędź.')
                p, d = tw.edge_axis(body.shape.Edges()[hit[1]])
                self.tx_line = dict(p=p, d=d, label=f'Krawędź {hit[1] + 1} — {body.name}')
                self.view._set_hover_edge(None)
            else:
                face = self._tx_face_at(x, y)
                if face is None:
                    raise kernel.CadError('Kliknij powierzchnię walcową bryły.')
                p, d = tw.cylinder_axis(face)
                self.tx_line = dict(p=p, d=d, label=f'Oś walca R {self._tx_radius(face):g} mm'.replace('.', ','))
                self.view.set_hover_mesh(None)
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        self._tx_refresh()

    @staticmethod
    def _tx_radius(face):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        return round(BRepAdaptor_Surface(face.wrapped).Cylinder().Radius(), 3)

    def _tx_kind_changed(self):
        self.tx_points, self.tx_line = [], None
        self.view.hover_vertex = None
        self.view._set_hover_edge(None)
        self.view.set_hover_mesh(None)
        self._tx_kind_widgets()
        self._tx_refresh()

    def _tx_kind_widgets(self):
        kind = self.tx_kind.currentData()
        fixed = kind in ('global', 'local')
        self.tx_axis.setVisible(fixed)
        self.tx_axis_label.setVisible(fixed)
        self.tx_axis_label.setText('Oś globalna' if kind == 'global' else 'Oś lokalna bryły')
        self.tx_info.setText(KIND_HINTS[kind])
        self.tx_step2.icon_kind = dict((k, i) for _, k, i in TWIST_KINDS)[kind]
        from .studio import TOOLS_TOP
        self._fit_panel(self.twist_panel, 88 + TOOLS_TOP - 18)

    # ---------- oś skręcenia ----------
    def twist_axis_spec(self):
        """Opis osi (do zapisu w kolejnych etapach): kind, axis, p, d, reverse."""
        kind = self.tx_kind.currentData()
        spec = dict(kind=kind, axis=self.tx_axis.currentData(), reverse=self.tx_reverse.isChecked())
        if kind == 'points' and len(self.tx_points) == 2:
            p, d = tw.points_axis(*self.tx_points)
            spec.update(p=[float(c) for c in p], d=[float(c) for c in d])
        elif kind in ('edge', 'cyl') and self.tx_line is not None:
            spec.update(p=[float(c) for c in self.tx_line['p']], d=[float(c) for c in self.tx_line['d']])
        return spec

    def _tx_base(self, body):
        """(kształt, siatka) skręcanej bryły: bieżąca bryła albo - przy przebudowie - zapisany kształt źródłowy."""
        rebuild = self._tx_rebuild
        if rebuild is not None and body is not None and rebuild['id'] == body.id:
            if rebuild.get('mesh') is None:
                rebuild['mesh'] = kernel.display_mesh(rebuild['shape'])
            return rebuild['shape'], rebuild['mesh']
        return (body.shape, body.mesh) if body is not None else (None, None)

    def twist_axis(self):
        """(punkt, kierunek) osi skręcenia albo None, gdy oś nie jest jeszcze wskazana."""
        body = self._tx_solid(self.tx_id)
        if body is None:
            return None
        spec = self.twist_axis_spec()
        if spec['kind'] in ('points', 'edge', 'cyl') and spec.get('p') is None:
            return None
        shape = self._tx_base(body)[0]
        key = (id(shape), repr(sorted(spec.items())))
        hit = self._tx_cache.get('axis')
        if hit is None or hit[0] != key:
            hit = self._tx_cache['axis'] = (key, tw.resolve(spec, shape))
        return hit[1]

    def twist_params(self):
        """Parametry skręcenia z panelu: dict(id, angle (°), axis 'X' / 'Y' / 'Z', kind, reverse, origin, direction)."""
        spec = self.twist_axis_spec()
        axis = self.twist_axis()
        return dict(id=self.tx_id, angle=float(self.tx_angle.value()), axis=spec['axis'], kind=spec['kind'], reverse=spec['reverse'],
                    origin=None if axis is None else [float(c) for c in axis[0]],
                    direction=None if axis is None else [float(c) for c in axis[1]],
                    range_from=round(self.tx_from.value() / 100.0, 6), range_to=round(self.tx_to.value() / 100.0, 6),
                    distribution=self.tx_dist.currentData(), anchor=self.tx_anchor.currentData(), tolerance=float(self.tx_tol.value()))

    def _tx_check(self):
        """Komunikat błędu albo None, gdy wybór i parametry są poprawne."""
        if self._tx_solid(self.tx_id) is None:
            return 'Kliknij bryłę do skręcenia.'
        if abs(self.tx_angle.value()) < 1e-9:
            return 'Kąt skręcenia musi być różny od zera.'
        if self.tx_to.value() - self.tx_from.value() < .1:
            return 'Zakres skręcenia: koniec musi być za początkiem.'
        kind = self.tx_kind.currentData()
        try:
            axis = self.twist_axis()
        except kernel.CadError as exc:
            return str(exc)
        if axis is None:
            if kind == 'points':
                return f'Kliknij {"drugi" if self.tx_points else "pierwszy"} punkt osi.'
            return KIND_HINTS[kind]
        return None

    # ---------- widok: oś i manipulator ----------
    def _tx_angle_changed(self):
        self._tx_status()
        self._tx_place_ring()
        self._tx_timer.start()

    def _tx_refresh(self):
        self._tx_status()
        self._tx_show_axis()
        self._tx_place_ring()
        self._tx_timer.start()

    def _tx_status(self):
        error = self._tx_check()
        kind = self.tx_kind.currentData()
        done = error is None or (self._tx_solid(self.tx_id) is not None and self._tx_axis_ready())
        label = {'global': f'Globalna {self.tx_axis.currentData()}', 'local': f'Lokalna {self.tx_axis.currentData()}',
                 'points': 'Przez 2 punkty', 'edge': (self.tx_line or {}).get('label', 'Krawędź'), 'cyl': (self.tx_line or {}).get('label', 'Oś walca')}[kind]
        self.tx_step2.set_state('done' if done else 'active', label + (' (odwrócona)' if self.tx_reverse.isChecked() and done else ''))
        names = {'linear': 'liniowy', 'smoothstep': 'płynny', 'progressive': 'progresywny', 'start': 'początek', 'center': 'środek', 'end': 'koniec'}
        self.tx_step3.set_state('done', f'{self.tx_from.value():g}–{self.tx_to.value():g} % · {names[self.tx_dist.currentData()]} · '
                                        f'w miejscu: {names[self.tx_anchor.currentData()]}'.replace('.', ','))
        if error:
            self.tx_status.setText(error)
            return
        p = self.twist_params()
        self.tx_status.setText(f'{p["angle"]:g}° · {label} · Enter zatwierdza'.replace('.', ','))

    def _tx_axis_ready(self):
        try:
            return self.twist_axis() is not None
        except kernel.CadError:
            return False

    def _tx_geometry(self):
        """(punkt, kierunek, t_min, t_max, promień) - oś i zasięg bryły wzdłuż niej; None, gdy osi jeszcze nie ma."""
        body = self._tx_solid(self.tx_id)
        try:
            axis = self.twist_axis()
        except kernel.CadError:
            axis = None
        if body is None or axis is None:
            return None
        origin, direction = axis
        shape, mesh = self._tx_base(body)
        points = mesh.vertices if mesh is not None and len(mesh.vertices) else [v.toTuple() for v in shape.Vertices()]
        t0, t1, radius = tw.extent(points, origin, direction)
        return origin, direction, t0, t1, radius

    def _tx_show_axis(self):
        """Linia osi przez całą bryłę (z zapasem) i stożek grotu na końcu - kierunek osi; wskazane punkty jako kropki."""
        self.view.sel_vertices = list(self.tx_points) if self.tx_kind.currentData() == 'points' else []
        geo = self._tx_geometry()
        if geo is None:
            self.view.set_selection_meshes(None)
            self.view.overlay.update()
            return
        origin, direction, t0, t1, radius = geo
        size = max(t1 - t0, radius, 1.0)
        margin = .18 * size
        a, b = origin + direction * (t0 - margin), origin + direction * (t1 + margin)
        head = max(.06 * size, .8)
        e1, e2 = tw.ring_basis(direction)
        base = b - direction * head
        rim = [base + head * .38 * (math.cos(t) * e1 + math.sin(t) * e2) for t in np.linspace(0, 2 * math.pi, 17)[:-1]]
        vertices = np.array([b, *rim], np.float32)
        triangles = np.array([(0, i + 1, (i + 1) % len(rim) + 1) for i in range(len(rim))], np.uint32)
        line = np.array([a, b], np.float32)
        mesh = kernel.DisplayMesh(vertices, triangles, {0: line}, tuple(float(c) for c in (a + b) / 2), float(size))
        self.view.set_selection_meshes([mesh], color=(.94, .42, .05, .95), line_color=AXIS_LINE)
        self.view.overlay.update()

    def _tx_ring(self):
        geo = self._tx_geometry()
        if geo is None:
            return None
        origin, direction, t0, t1, radius = geo
        size = max(t1 - t0, radius, 1.0)
        r = max(radius * 1.15, .25 * size, 2.0)
        return origin + direction * t1, direction, r

    def _tx_place_ring(self):
        """Manipulator obrotowy przy końcu bryły (pierścień z systemu uchwytów widoku): łuk od kąta 0 pokazuje kierunek
        i wartość skręcenia, przeciąganie pierścienia zmienia kąt."""
        ring = self._tx_ring() if self.mode == 'twist' else None
        if ring is None:
            self.view.set_handles([])
            return
        c, axis, r = ring
        sweep = math.radians(self.tx_angle.value())
        e1, e2 = tw.ring_basis(axis)
        tip = c + r * (math.cos(sweep) * e1 + math.sin(sweep) * e2)
        text = f'{self.tx_angle.value():g}°'.replace('.', ',')
        self.view.set_handles([dict(id='tx', kind='ring', ring=(c, axis, r), tip=tip, dir=np.cross(axis, e1), color=RING_COLOR,
                                    label='', sweep=sweep, text=text)])

    def twist_handle_dragged(self, delta):
        ring = self._tx_ring()
        if ring is None:
            return
        if self._hv is None:
            self._hv = self.tx_angle.value()
        self.tx_angle.setValue(round(self._hv + math.degrees(delta / ring[2]), 1))

    # ---------- szybki podgląd skręcenia (kopia siatki wyświetlania) ----------
    def _tx_field(self):
        """Pole skręcenia podglądu (zakres, rozkład i zakotwiczenie z okna) albo None."""
        geo = self._tx_geometry()
        if geo is None or self._tx_check() is not None:
            return None
        origin, direction, t0, t1, _ = geo
        try:
            return tm.field_for_extent(origin, direction, self.tx_angle.value(), t0, t1, self.tx_from.value() / 100.0,
                                       self.tx_to.value() / 100.0, self.tx_dist.currentData(), 2.0, self.tx_anchor.currentData())
        except tm.TwistParamError:
            return None

    def _tx_preview(self):
        """Podgląd: pocięta kopia siatki (pamięć podręczna dla bryły, osi i liczby warstw) obrócona polem skręcenia.
        Oryginał ukryty tylko w widoku; przy błędzie parametrów - oryginalny widok."""
        if self.mode != 'twist':
            return
        body = self._tx_solid(self.tx_id)
        mesh = self._tx_base(body)[1]
        field = self._tx_field() if mesh is not None and len(mesh.triangles) else None
        if field is None:
            self._tx_preview_clear()
            return
        layers = tp.layer_count(field.angle, field.kind, field.power, len(mesh.triangles))
        key = (id(mesh), field.origin, field.direction, field.start, field.end, layers)
        hit = self._tx_cache.get('sliced')
        if hit is None or hit[0] != key:
            sliced = tp.SlicedMesh(mesh.vertices, mesh.triangles, mesh.edges, field.origin, field.direction,
                                   tp.cut_planes(field.start, field.end, layers))
            hit = self._tx_cache['sliced'] = (key, sliced)
        vertices, edges = hit[1].twisted(field)
        preview = kernel.DisplayMesh(vertices.astype(np.float32), hit[1].triangles.astype(np.uint32),
                                     {k: e.astype(np.float32) for k, e in edges.items()}, mesh.center, mesh.size)
        self.twist_preview_mesh = preview
        self.view.set_preview_mesh(preview, color=PREVIEW_COLOR, line_color=PREVIEW_LINE, width=1.6)
        if self.override.get(body.id) is None or set(self.override) != {body.id}:
            self.override = {body.id: replace(body, visible=False)}     # oryginał ukryty tylko w widoku
            self.refresh()

    def _tx_preview_clear(self):
        self.twist_preview_mesh = None
        self.view.set_preview_mesh(None)
        if self.override:
            self.override = {}
            self.refresh()

    # ---------- zatwierdzenie / anulowanie ----------
    def twist_recipe(self):
        """Przepis kroku historii 'twist' (history.run_twist): bryła źródłowa, oś (opis i wyznaczony punkt / kierunek),
        kąt, zakres, rozkład, zakotwiczenie, tolerancja; przy przebudowie - także kształt źródłowy."""
        p = self.twist_params()
        recipe = dict(type='twist', id=self.tx_id, angle=p['angle'], axis=self.twist_axis_spec(), origin=p['origin'],
                      direction=p['direction'], range_from=p['range_from'], range_to=p['range_to'], kind=p['distribution'],
                      power=2.0, anchor=p['anchor'], tolerance=p['tolerance'])
        if self._tx_rebuild is not None and self._tx_rebuild['id'] == self.tx_id:
            recipe['source'] = self._tx_rebuild['source']
        return recipe

    # ---------- ponowna edycja (krok historii, dwuklik w bryłę, bryła z biblioteki) ----------
    def set_twist_params(self, params):
        """Okno TWIST z parametrami z przepisu / meta['twist'] (bez zmiany wybranej bryły)."""
        axis = dict(params.get('axis') or {})
        widgets = (self.tx_angle, self.tx_from, self.tx_to, self.tx_tol, self.tx_axis, self.tx_kind, self.tx_reverse, self.tx_dist, self.tx_anchor)
        for w in widgets:
            w.blockSignals(True)
        self.tx_angle.setValue(float(params.get('angle', 90.0)))
        self.tx_from.setValue(100.0 * float(params.get('range_from', 0.0)))
        self.tx_to.setValue(100.0 * float(params.get('range_to', 1.0)))
        self.tx_tol.setValue(float(params.get('tolerance', DEFAULT_TOLERANCE)))
        self.tx_kind.setCurrentIndex([k for _, k, _ in TWIST_KINDS].index(axis.get('kind', 'global')))
        self.tx_axis.setCurrentIndex('XYZ'.index(axis.get('axis', 'Z')))
        self.tx_reverse.setChecked(bool(axis.get('reverse')))
        self.tx_dist.setCurrentIndex([k for _, k, _ in DISTRIBUTION_ITEMS].index(params.get('kind', 'linear')))
        self.tx_anchor.setCurrentIndex([k for _, k, _ in ANCHOR_ITEMS].index(params.get('anchor', 'start')))
        for w in widgets:
            w.blockSignals(False)
        self.tx_points, self.tx_line = [], None
        if axis.get('p') is not None and axis.get('d') is not None:
            p, d = np.asarray(axis['p'], float), np.asarray(axis['d'], float)
            if axis.get('kind') == 'points':
                self.tx_points = [p, p + d]
            elif axis.get('kind') in ('edge', 'cyl'):
                self.tx_line = dict(p=p, d=d, label='Krawędź (z kroku)' if axis['kind'] == 'edge' else 'Oś walca (z kroku)')
        self._tx_cache = {}
        self._tx_kind_widgets()
        self._tx_refresh()

    def _step_fill_twist(self, recipe):
        """Edycja kroku historii (dwuklik w krok / bryłę, Edytuj parametry): okno z wartościami kroku na modelu sprzed
        niego; Zastosuj zastępuje krok, dalsze kroki przeliczają się (mechanizm edycji kroków programu)."""
        body = self._tx_solid(recipe['id'])
        if body is None:
            raise kernel.CadError('brak bryły')
        if recipe.get('source'):
            self._tx_rebuild = dict(id=body.id, source=recipe['source'], shape=hist.twist_source_shape(recipe['source']))
        self._tx_set(body.id)
        self.set_twist_params(recipe)

    def twist_step_index(self, body_id):
        """Numer ostatniego kroku 'twist' tej bryły w historii albo None."""
        found = None
        for index, (_, info) in enumerate(self.document.states()):
            op = info.get('op') or {}
            if op.get('type') == 'twist' and op.get('id') == body_id:
                found = index
        return found

    def edit_twist(self, body_id):
        """Dwuklik w skręconą bryłę: krok TWIST z historii (gdy jest - dalsze kroki zostają i się przeliczą), inaczej
        przebudowa z kształtu źródłowego zapisanego w bryle (np. bryła wstawiona z biblioteki)."""
        body = self._tx_solid(body_id)
        twist = ((body.meta or {}).get('twist') if body is not None else None)
        if twist is None or self.busy:
            return False
        index = self.twist_step_index(body_id)
        if index is not None:
            self.history_edit(index)
            return True
        self.set_mode('twist')
        self._tx_rebuild = dict(id=body.id, source=twist['source'], shape=hist.twist_source_shape(twist['source']))
        self._tx_set(body.id)
        self.set_twist_params(twist)
        self.toast('Bryła skręcona (np. z biblioteki): zmień parametry i kliknij Zastosuj - bryła zostanie przebudowana z kształtu sprzed skręcenia.', 6000)
        return True

    def apply_twist(self):
        """Etap 5: rzeczywiste skręcenie bryły B-Rep (rccad.twist_occ) w tle, jako krok historii (cofnij / ponów, zapis).
        Siatka podglądu nie jest używana - bryła liczy się od nowa z geometrii Open CASCADE. Błąd: komunikat, okno
        zostaje otwarte, oryginał bez zmian."""
        if self.busy or self.mode != 'twist':
            return
        error = self._tx_check()
        if error:
            self.toast(error)
            return
        self._tx_timer.stop()
        recipe = self.twist_recipe()
        existing = list(self.document.bodies)

        def build():
            return list(hist.run_twist(existing, recipe))

        def apply(bodies):
            self.document.pending_op = recipe
            self.document.pending_label = 'Skręcenie (TWIST)'
            self.document.pending_icon = 'twist'
            self.document.commit(bodies)
            self.selected = [recipe['id']]

        self.run_operation('Skręcenie (TWIST)', build, apply, after=lambda: self.set_mode(None))

    def cancel_twist(self):
        self._tx_timer.stop()
        self.set_mode(None)          # set_mode czyści podgląd i podmianę widoku (override), refresh pokazuje oryginał
