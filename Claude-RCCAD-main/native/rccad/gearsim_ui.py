"""Przekładnie → Symulacja przekładni (zakładka Przekładnie).

Mixin okna Studio - tylko interfejs. Kinematykę i kolizje liczy silnik rccad.gears.kinematics (bez Qt).
Para: koło pary z narzędzia Para kół (drugie koło znajduje się samo) albo dowolne dwa koła z parametrami (zaznaczone
przed otwarciem albo klikane w widoku). Start / Stop / Reset, prędkość obrotowa koła napędzającego (obr/min),
kierunek, wybór koła napędzającego i tempo animacji. Animacja zmienia tylko macierze brył w widoku
(view.set_body_matrices) - geometria B-Rep i model zostają bez zmian; Reset i wyjście z narzędzia przywracają położenie.
Kontrola kolizji w każdej klatce (przekroje czołowe) i przegląd całej podziałki zęba po wybraniu pary."""
from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QMatrix4x4
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from . import shell_ui as ui
from .gear_ui import READOUT
from .gears import GearError, GearParams
from .gears import kinematics as km

FRAME_MS = 33
GAP_EVERY = 6           # odstęp zębów (informacja) co tyle klatek - kolizja sprawdzana w każdej


class GearSimTools:
    def _build_gearsim_panel(self):
        from .studio import _label, _spin
        self.gearsim_panel, lay = self._panel(320, 'Symulacja przekładni', 'x_gearsim', 'Przekładnie · obrót kół w zazębieniu', plain=True, scroll=True)
        self.gs_step1 = ui.StepRow(1, 'x_gearpair', 'Para kół', plain=True)
        lay.addWidget(self.gs_step1)
        self.gs_pair_label = _label('Kliknij koło pary w widoku (albo dwa koła po kolei).', 'small')
        self.gs_pair_label.setWordWrap(True)
        lay.addWidget(self.gs_pair_label)
        self.gs_step2 = ui.StepRow(2, 'x_gearsim', 'Napęd', plain=True)
        lay.addWidget(self.gs_step2)
        lay.addWidget(_label('Koło napędzające'))
        self.gs_driver = ui.Segmented([('Koło 1', 0, 'gr_body'), ('Koło 2', 1, 'gr_body')], 26)
        self.gs_driver.currentIndexChanged.connect(lambda *_: self._gs_changed(reset=True))
        lay.addWidget(self.gs_driver)
        lay.addWidget(_label('Prędkość wejściowa (obr/min)'))
        self.gs_rpm = _spin(30.0, 0, 1e6, 2, 5)
        self.gs_rpm.setToolTip('Prędkość obrotowa koła napędzającego.')
        self.gs_rpm.valueChanged.connect(lambda *_: self._gs_changed())
        lay.addWidget(self.gs_rpm)
        lay.addWidget(_label('Kierunek koła napędzającego'))
        self.gs_dir = ui.Segmented([('W lewo', 1, 'gs_ccw'), ('W prawo', -1, 'gs_cw')], 26)
        self.gs_dir._buttons[0].setToolTip('Przeciwnie do ruchu wskazówek zegara (patrząc wzdłuż osi koła 1 od jej końca).')
        self.gs_dir._buttons[1].setToolTip('Zgodnie z ruchem wskazówek zegara.')
        self.gs_dir.currentIndexChanged.connect(lambda *_: self._gs_changed())
        lay.addWidget(self.gs_dir)
        lay.addWidget(_label('Tempo animacji (%)'))
        self.gs_tempo = _spin(100.0, .1, 100, 1, 10)
        self.gs_tempo.setToolTip('Spowolnienie animacji (100% - prędkość rzeczywista). Prędkości w ramce - zawsze rzeczywiste.')
        self.gs_tempo.valueChanged.connect(lambda *_: self._gs_changed())
        lay.addWidget(self.gs_tempo)
        self.gs_info = QLabel('—')
        self.gs_info.setObjectName('readout')
        self.gs_info.setWordWrap(True)
        self.gs_info.setTextFormat(Qt.RichText)
        self.gs_info.setStyleSheet(READOUT)
        lay.addWidget(self.gs_info)
        self.gs_status = _label('', 'status')
        self.gs_status.setWordWrap(True)
        self.gs_status.setTextFormat(Qt.RichText)
        lay.addWidget(self.gs_status)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.gs_run_btn, self.gs_reset_btn, self.gs_close_btn = QPushButton('Start'), QPushButton('Reset'), QPushButton('Zamknij')
        self.gs_run_btn.setObjectName('primary')
        self.gs_run_btn.setToolTip('Uruchamia / zatrzymuje obrót kół (Enter).')
        self.gs_reset_btn.setToolTip('Zatrzymuje i ustawia koła w położeniu z modelu.')
        self.gs_close_btn.setToolTip('Kończy symulację - koła wracają do położenia z modelu.')
        self.gs_run_btn.clicked.connect(lambda _=False: self.toggle_gearsim())
        self.gs_reset_btn.clicked.connect(lambda _=False: self.reset_gearsim())
        self.gs_close_btn.clicked.connect(lambda _=False: self.set_mode(None))
        for b in (self.gs_run_btn, self.gs_reset_btn, self.gs_close_btn):
            row.addWidget(b)
        self.gearsim_panel.footer.addLayout(row)
        self.gs_sim = None
        self.gs_first = None                          # pierwsze kliknięte koło (para z dwóch dowolnych kół)
        self.gs_theta = 0.0                           # kąt koła napędzającego (rad)
        self.gs_running = False
        self.gs_last = None
        self.gs_result = None
        self.gs_sweep = None
        self._gs_timer = QTimer(self)
        self._gs_timer.setInterval(FRAME_MS)
        self._gs_timer.timeout.connect(self._gs_tick)
        self._gs_changed()

    # ---------- wybór pary ----------
    def _gearsim_enter(self):
        self.gearsim_panel.show()
        self.gs_first = None
        self.gs_theta, self.gs_running = 0.0, False
        previous = [self.document.get(w.id) for w in self.gs_sim.wheels] if self.gs_sim is not None else []
        self.gs_sim = None
        for identifier in list(self.selected):
            if self._gs_try(identifier, quiet=True):
                break
        if self.gs_sim is None and len(previous) == 2 and all(previous):
            self._gs_set_pair(*previous, quiet=True)   # ta sama para co poprzednio - z aktualnymi położeniami kół
        self._gs_changed(reset=True)
        self.view.setCursor(Qt.ArrowCursor)
        self.hint('Symulacja przekładni: kliknij koło pary (albo dwa koła), potem Start. Animacja nie zmienia modelu.')

    def _gearsim_leave(self):
        self._gs_timer.stop()
        self.gs_running = False
        self.gs_theta = 0.0
        self.view.clear_body_matrices()

    def _gs_wheel(self, body):
        params = (body.meta or {}).get('gear')
        if params is None:
            return None
        return km.Wheel(body.id, GearParams.from_dict(params), km._m4((body.meta or {}).get('gear_place')))

    def _gs_partner(self, body):
        """Drugie koło pary utworzonej narzędziem Para kół (ten sam identyfikator pary)."""
        key = ((body.meta or {}).get('gear_pair') or {}).get('pair')
        if not key:
            return None
        return next((b for b in self.document.bodies if b.id != body.id and ((b.meta or {}).get('gear_pair') or {}).get('pair') == key), None)

    def _gs_try(self, identifier, quiet=False):
        body = self.document.get(identifier)
        if body is None or self._gs_wheel(body) is None:
            if not quiet:
                self.toast('To nie jest koło zębate z generatora - kliknij koło (z parametrami).')
            return False
        partner = self._gs_partner(body)
        if partner is None and self.gs_first is not None and self.gs_first != body.id and self.document.get(self.gs_first) is not None:
            partner = self.document.get(self.gs_first)
        if partner is None:
            self.gs_first = body.id
            self.gs_pair_label.setText(f'Koło: {body.name}. Kliknij drugie koło.')
            return False
        return self._gs_set_pair(body, partner, quiet)

    def _gs_set_pair(self, a, b, quiet=False):
        self._gs_stop()
        self.view.clear_body_matrices()
        role = lambda body: ((body.meta or {}).get('gear_pair') or {}).get('role', 9)
        if role(b) < role(a):                         # koła z pary - w kolejności z okna Para kół (koło 1, koło 2)
            a, b = b, a
        try:
            sim = km.Simulation(self._gs_wheel(a), self._gs_wheel(b))
        except GearError as exc:
            self.gs_sim, self.gs_first = None, None
            self.gs_status.setText(f'<span style="color:#c4373c;font-weight:700;">✖ {exc}</span>')
            if not quiet:
                self.toast(str(exc))
            return False
        self.gs_sim, self.gs_first, self.gs_theta = sim, None, 0.0
        names = [self.document.get(w.id).name for w in sim.wheels]
        self.gs_pair_label.setText(f'Koło 1: {names[0]}<br>Koło 2: {names[1]}')
        self.gs_pair_label.setTextFormat(Qt.RichText)
        for button, name in zip(self.gs_driver._buttons, names):
            button.setToolTip(f'Napędza {name}.')
        self.gs_sweep = sim.sweep(0)                  # przegląd całej podziałki zęba (ruch względny - raz dla pary)
        self._gs_changed(reset=True)
        return True

    def pick_gearsim(self, x, y):
        hit = self.view.pick_face(x, y)
        if not hit:
            return
        self._gs_try(hit[0])

    # ---------- animacja ----------
    def _gs_omega(self):
        """Prędkość kątowa koła napędzającego w animacji (rad/s) z kierunkiem i tempem."""
        return self.gs_dir.currentData() * self.gs_rpm.value() * 2 * math.pi / 60 * self.gs_tempo.value() / 100

    def toggle_gearsim(self):
        if self.gs_sim is None:
            self.toast('Najpierw wybierz parę kół - kliknij koło w widoku.')
            return
        if self.gs_running:
            self._gs_stop()
        else:
            self.gs_running = True
            self.gs_last = time.monotonic()
            self._gs_timer.start()
        self._gs_changed()

    def _gs_stop(self):
        self.gs_running = False
        self._gs_timer.stop()

    def reset_gearsim(self):
        self._gs_stop()
        self.gs_theta = 0.0
        self.view.clear_body_matrices()
        self._gs_changed(reset=True)

    def gearsim_step(self, dt):
        """Jedna klatka: obrót koła napędzającego o ω·dt (dt w sekundach) - macierze brył w widoku i kontrola kolizji."""
        if self.gs_sim is None:
            return
        self.gs_theta += self._gs_omega() * dt
        self._gs_show()

    def _gs_tick(self):
        now = time.monotonic()
        dt, self.gs_last = now - (self.gs_last or now), now
        self.gearsim_step(min(dt, .2))

    def _gs_show(self):
        sim = self.gs_sim
        angles = sim.angles(self.gs_driver.currentData(), self.gs_theta)
        matrices = sim.matrices(*angles)
        self.view.set_body_matrices({identifier: QMatrix4x4(*np.asarray(m, float).flatten()) for identifier, m in matrices.items()})
        self.gs_frame = getattr(self, 'gs_frame', 0) + 1
        gap_due = self.gs_frame % GAP_EVERY == 0 or self.gs_result is None
        result = sim.check(*angles, with_gap=gap_due)    # kolizja w każdej klatce, odstęp zębów co kilka klatek
        if not gap_due:
            result['gap'] = self.gs_result.get('gap')
        self.gs_result = result
        self._gs_info()

    def _gs_changed(self, reset=False):
        if reset and self.gs_sim is not None:
            self.gs_result = self.gs_sim.check(*self.gs_sim.angles(self.gs_driver.currentData(), self.gs_theta))
        self.gs_run_btn.setText('Stop' if self.gs_running else 'Start')
        self.gs_run_btn.setEnabled(self.gs_sim is not None)
        self.gs_reset_btn.setEnabled(self.gs_sim is not None)
        self.gs_step1.set_state('done' if self.gs_sim else 'active', 'wybrana' if self.gs_sim else 'kliknij koło')
        self.gs_step2.set_state('done' if self.gs_sim else 'pending', f'{self.gs_rpm.value():g} obr/min')
        self._gs_info()

    def _gs_info(self):
        sim = self.gs_sim
        if sim is None:
            self.gs_info.setText('Wybierz parę kół - kliknij koło w widoku.')
            return
        driver = self.gs_driver.currentData()
        rpm = self.gs_rpm.value()
        out, same = sim.speeds(driver, rpm)
        wise = lambda sign: 'w lewo' if sign > 0 else 'w prawo'
        sign_in = self.gs_dir.currentData()
        sign_out = sign_in if same else -sign_in
        z = [w.params.teeth for w in sim.wheels]
        rows = [f'Przełożenie i = z<sub>{2 - driver}</sub> / z<sub>{driver + 1}</sub>: <b>{z[1 - driver] / z[driver]:.4f}</b>',
                f'Prędkość wejściowa (koło {driver + 1}): <b>{rpm:.2f} obr/min</b> {wise(sign_in)}',
                f'Prędkość wyjściowa (koło {2 - driver}): <b>{out:.2f} obr/min</b> {wise(sign_out)}',
                f'Odległość osi: <b>{sim.center:.4f} mm</b> (stała)',
                f'Obrót koła napędzającego: <b>{math.degrees(self.gs_theta) % 360:.1f}°</b>']
        self.gs_info.setText('<br>'.join(rows))
        lines = []
        result, sweep = self.gs_result, self.gs_sweep
        if not sim.engaged:
            lines.append('<span style="color:#9a6512;">⚠ Koła się nie zazębiają (za duża odległość osi) - obracają się niezależnie.</span>')
        if result is not None and result['collision']:
            lines.append(f'<span style="color:#c4373c;font-weight:700;">✖ Kolizja zębów: wspólne pole przekroju {result["overlap"]:.3f} mm².</span>')
        elif sweep is not None and sweep[0] > km.OVERLAP_TOL:
            lines.append(f'<span style="color:#c4373c;font-weight:700;">✖ Kolizja zębów w trakcie obrotu (wspólne pole do {sweep[0]:.3f} mm²).</span>')
        else:
            gap = result['gap'] if result else None
            text = f' - odstęp zębów teraz {gap:.3f} mm' if gap is not None else ''
            low = f', najmniejszy w obrocie {sweep[1]:.3f} mm' if sweep and sweep[1] is not None else ''
            lines.append(f'<span style="color:#22794f;font-weight:700;">✔ Brak kolizji{text}{low} (przekrój czołowy).</span>')
        self.gs_status.setText('<br>'.join(lines))
