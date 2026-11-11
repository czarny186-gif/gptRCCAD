"""Wyrównaj rozmiar (zakładka Szkic): kształty tego samego rodzaju dostają wymiary wzorca.

Mixin okna Studio. Pierwszy kliknięty szkic jest wzorcem, każdy kolejny kształt tego samego rodzaju od razu (na polu
roboczym) przyjmuje jego wymiary - środek zostaje w miejscu. Zastosuj zapisuje zmiany jako jeden krok historii
('multi' z krokami 'sketchmeta'), Zamknij zamyka okno i przywraca poprzednie wymiary."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from . import kernel
from . import shell_ui as ui
from . import sketchmeta as sm

TINT_REFERENCE = (.96, .62, .18, .55)
TINT_MATCHED = (.3, .78, .5, .55)


class MatchSizeTools:
    def _build_matchsize_panel(self):
        from .studio import _label
        self.matchsize_panel, lay = self._panel(296, 'Wyrównaj rozmiar', 'x_matchsize', 'Ten sam rozmiar kształtów', plain=True, scroll=True)
        lay.addWidget(ui.StepRow(1, 'x_matchsize', 'Wybierz szkic wzorcowy', plain=True))
        self.mz_ref_label = _label('', 'status')
        self.mz_ref_label.setWordWrap(True)
        lay.addWidget(self.mz_ref_label)
        lay.addWidget(ui.StepRow(2, 'x_object', 'Klikaj takie same kształty', plain=True))
        self.mz_status = _label('', 'status')
        self.mz_status.setWordWrap(True)
        lay.addWidget(self.mz_status)
        self.mz_reset = QPushButton('Wybierz inny wzorzec')
        self.mz_reset.setToolTip('Cofa zmiany z tego okna i pozwala wskazać nowy wzorzec.')
        self.mz_reset.clicked.connect(lambda _=False: self._mz_start())
        lay.addWidget(self.mz_reset)
        help_ = _label('Działa tylko dla kształtów tego samego rodzaju (prostokąt z prostokątem, okrąg z okręgiem...). '
                       'Środek kształtu zostaje w miejscu. Ponowne kliknięcie zmienionego kształtu przywraca jego rozmiar.', 'help')
        help_.setWordWrap(True)
        lay.addWidget(help_)
        self.mz_apply, close = self._buttons(self.matchsize_panel.footer, 'Zastosuj', 'Zamknij', self.apply_matchsize, lambda: self.set_mode(None))
        self.mz_apply.setToolTip('Zapisuje nowe wymiary (jeden krok historii, można cofnąć).')
        close.setToolTip('Zamyka okno. Niezastosowane zmiany wymiarów są cofane.')
        self.mz_ref = None
        self.mz_pending = {}

    def _matchsize_enter(self):
        self.matchsize_panel.show()
        self.view.setCursor(Qt.PointingHandCursor)
        self._mz_start()

    def _mz_start(self):
        self.mz_ref = None
        self.mz_pending = {}
        self.override = {}
        self._mz_refresh()
        self.hint('Wyrównaj rozmiar: kliknij szkic wzorcowy, potem kształty, które mają mieć jego wymiary.')

    def _mz_pick_sketch(self, x, y):
        hit = self.view.nearest_edge(x, y, kinds=('sketch',))
        body = self.document.get(hit[0]) if hit else None
        if body is None:
            bid = self.view.pick_body(x, y)
            body = self.document.get(bid) if bid else None
        return body if body is not None and body.kind == 'sketch' else None

    def pick_matchsize(self, x, y):
        body = self._mz_pick_sketch(x, y)
        if body is None:
            self.toast('Kliknij kształt szkicu.')
            return
        if sm.family(body.meta) is None:
            self.toast('Tego szkicu nie da się wymiarować (np. tekst albo kształt po przycięciu).')
            return
        if self.mz_ref is None:
            self.mz_ref = body.id
            self._mz_refresh()
            return
        if body.id == self.mz_ref:
            return
        if body.id in self.mz_pending:               # ponowny klik - kształt wraca do swojego rozmiaru
            del self.mz_pending[body.id]
            self._mz_refresh()
            return
        ref = self.document.get(self.mz_ref)
        meta = sm.match_size(ref.meta, body.meta)
        if meta is None:
            self.toast(f'To nie ten sam kształt: wzorzec to {sm.family_name(ref.meta)}, kliknięty - {sm.family_name(body.meta)}.', 3000)
            return
        try:
            shape = self._meta_shape(body.plane, meta)
            mesh = kernel.display_mesh(shape)
        except Exception as error:
            self.toast(f'Nie można zmienić rozmiaru: {error}', 3000)
            return
        self.mz_pending[body.id] = replace(body, shape=shape, mesh=mesh, meta=meta)
        self._mz_refresh()

    def _mz_refresh(self):
        if not hasattr(self, 'mz_status'):
            return
        live = {b.id: b for b in self.document.bodies}
        if self.mz_ref not in live:
            self.mz_ref = None
        self.mz_pending = {i: b for i, b in self.mz_pending.items() if i in live}
        ref = live.get(self.mz_ref)
        if ref is None:
            self.mz_ref_label.setText('Kliknij szkic, którego rozmiar mają przyjąć inne kształty.')
            self.mz_status.setText('')
        else:
            count = 1 if sm.FAMILY[ref.meta['tool']] in ('circle', 'line', 'polygon') else 2
            dims = ', '.join(f'{label.split(" (")[0].lower()} {value} mm'
                             for label, value in zip(sm.LABELS[ref.meta['tool']][:count], sm.values(ref.meta)[:count]))
            self.mz_ref_label.setText(f'Wzorzec: {ref.name} ({sm.family_name(ref.meta)})\n{dims}')
            n = len(self.mz_pending)
            self.mz_status.setText(f'Zmieniono kształtów: {n}. Zastosuj zapisuje nowe wymiary.' if n
                                   else f'Klikaj kształty: {sm.family_name(ref.meta)} - od razu przyjmą wymiary wzorca.')
        self.mz_apply.setEnabled(bool(self.mz_pending))
        self.mz_reset.setEnabled(ref is not None)
        if self.mode == 'matchsize':
            self.override = dict(self.mz_pending)
            tints = {i: TINT_MATCHED for i in self.mz_pending}
            if ref is not None:
                tints[ref.id] = TINT_REFERENCE
            self.view.tints = tints
            self.selected = [i for i in (self.mz_ref, *self.mz_pending) if i]
            self.refresh()

    def apply_matchsize(self):
        if self.busy:
            return
        if not self.mz_pending:
            self.toast('Brak zmian - kliknij kształty, które mają przyjąć rozmiar wzorca.')
            return
        changed = dict(self.mz_pending)
        steps = [dict(type='sketchmeta', id=i, meta=b.meta) for i, b in changed.items()]
        n = len(steps)
        self.document.pending_op = steps[0] if n == 1 else dict(type='multi', steps=steps)
        self.document.pending_label = f'Wyrównaj rozmiar: {n} ' + ('kształt' if n == 1 else 'kształty' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'kształtów')
        self.document.pending_icon = 'matchsize'
        self.mz_pending = {}
        self.override = {}
        self.document.commit([changed.get(b.id, b) for b in self.document.bodies])
        self._mz_refresh()
        self.refresh()
        self.toast('Zapisano nowe wymiary.', 2000)
