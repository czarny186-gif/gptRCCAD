"""TWIST – Skręcanie brył (zakładka Edycja), etap 1: przycisk, panel parametrów i wybór bryły.

Mixin okna Studio. Bryłę wybiera się istniejącym zaznaczeniem (zaznaczona przed włączeniem narzędzia albo kliknięta
na polu roboczym - podświetla się jak każde zaznaczenie). Parametry: kąt skręcenia w stopniach (domyślnie 90°)
i oś X / Y / Z. Enter = Zastosuj, Esc = Anuluj.

Na tym etapie Zastosuj tylko sprawdza wybór i parametry - deformacja geometrii (i krok historii) dochodzi
w kolejnych etapach, model zostaje bez zmian."""
from __future__ import annotations

from PySide6.QtCore import Qt

from . import shell_ui as ui

TWIST_AXES = (('X', 'X', 'tw_x'), ('Y', 'Y', 'tw_y'), ('Z', 'Z', 'tw_z'))


class TwistTools:
    def _build_twist_panel(self):
        from .studio import _label, _spin
        self.twist_panel, lay = self._panel(300, 'TWIST – Skręcanie', 'x_twist', 'Skręcenie bryły wokół osi', plain=True, scroll=True)
        self.tx_step = ui.StepRow(1, 'x_object', 'Bryła', plain=True)
        lay.addWidget(self.tx_step)
        self.tx_angle = _spin(90.0, -3600.0, 3600.0, 1, 5)
        self.tx_angle.setSuffix('°')
        self.tx_angle.setToolTip('Kąt skręcenia w stopniach: o tyle obróci się jeden koniec bryły względem drugiego (ujemny - w drugą stronę).')
        self._field(lay, 'Kąt skręcenia (°)', self.tx_angle)
        self.tx_axis = ui.Segmented(list(TWIST_AXES), 30)
        for button, axis in zip(self.tx_axis._buttons, 'XYZ'):
            button.setToolTip(f'Bryła skręca się wokół osi {axis} (przechodzącej przez jej środek).')
        self.tx_axis.setCurrentIndex(2)
        self._field(lay, 'Oś skręcenia', self.tx_axis)
        self.tx_status = _label('', 'status')
        self.tx_status.setWordWrap(True)
        lay.addWidget(self.tx_status)
        self.tx_apply, cancel = self._buttons(self.twist_panel.footer, 'Zastosuj', 'Anuluj', self.apply_twist, self.cancel_twist)
        self.tx_apply.setToolTip('Zatwierdza skręcenie (Enter).')
        cancel.setToolTip('Zamyka narzędzie bez zmian (Esc).')
        self.tx_id = None
        self.tx_angle.valueChanged.connect(lambda *_: self._tx_status())
        self.tx_axis.currentIndexChanged.connect(lambda *_: self._tx_status())

    # ---------- wejście / wybór bryły ----------
    def _twist_enter(self):
        self.twist_panel.show()
        self.view.setCursor(Qt.PointingHandCursor)
        self.tx_angle.blockSignals(True)
        self.tx_angle.setValue(90.0)
        self.tx_angle.blockSignals(False)
        self.tx_axis.setCurrentIndex(2)
        picked = next((i for i in self.selected if self._tx_solid(i) is not None), None)
        self._tx_set(picked)
        self.hint('TWIST: kliknij bryłę, ustaw kąt i oś; Enter zatwierdza, Esc anuluje.')

    def _tx_solid(self, bid):
        body = self.document.get(bid) if bid else None
        return body if body is not None and body.kind == 'solid' else None

    def pick_twist(self, x, y):
        body = self._tx_solid(self.view.pick_body(x, y))
        if body is None:
            self.toast('Kliknij bryłę do skręcenia.')
            return
        self._tx_set(body.id)

    def _tx_set(self, bid):
        self.tx_id = bid
        self.selected = [bid] if bid else []
        self.refresh()
        body = self._tx_solid(bid)
        self.tx_step.set_state('done' if body else 'active', body.name if body else '')
        self._tx_status()

    def twist_params(self):
        """Parametry skręcenia z panelu: dict(id, angle (°), axis 'X' / 'Y' / 'Z')."""
        return dict(id=self.tx_id, angle=float(self.tx_angle.value()), axis=self.tx_axis.currentData())

    def _tx_check(self):
        """Komunikat błędu albo None, gdy wybór i parametry są poprawne."""
        if self._tx_solid(self.tx_id) is None:
            return 'Kliknij bryłę do skręcenia.'
        if abs(self.tx_angle.value()) < 1e-9:
            return 'Kąt skręcenia musi być różny od zera.'
        return None

    def _tx_status(self):
        error = self._tx_check()
        if error:
            self.tx_status.setText(error)
            return
        p = self.twist_params()
        self.tx_status.setText(f'{p["angle"]:g}° wokół osi {p["axis"]} · Enter zatwierdza'.replace('.', ','))

    # ---------- zatwierdzenie / anulowanie ----------
    def apply_twist(self):
        if self.busy or self.mode != 'twist':
            return
        error = self._tx_check()
        if error:
            self.toast(error)
            return
        # etap 1: bez deformacji geometrii - model zostaje bez zmian
        p = self.twist_params()
        self.toast(f'TWIST: {p["angle"]:g}° wokół osi {p["axis"]}. Skręcanie geometrii zostanie dodane w kolejnym etapie - model bez zmian.')
        self.set_mode(None)

    def cancel_twist(self):
        self.set_mode(None)
