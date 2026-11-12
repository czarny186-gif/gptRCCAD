"""Połącz / Rozłącz (zakładka Edycja).

Mixin okna Studio. Połącz: wskazane bryły (co najmniej dwie, także całe grupy z listy Obiekty) zachowują się jak jedna -
zaznaczają się, przesuwają i tną inne bryły razem - ale nie są scalone (widać miejsca styku). Na liście Obiekty trafiają do
jednej wspólnej grupy. Rozłącz: kliknięcie jednej połączonej bryły wskazuje całe połączenie; Zatwierdź przywraca każdej
bryle jej poprzednią grupę. Bryła pod kursorem podświetla się przed kliknięciem, prawy przycisk odznacza, Zamknij anuluje."""
from __future__ import annotations

import uuid

from PySide6.QtCore import Qt

from . import history as hist
from . import shell_ui as ui

LINK_TINT = (.30, .55, .95, 1)


class LinkTools:
    def _build_link_panel(self):
        from .studio import _label
        self.link_panel, lay = self._panel(312, 'Połącz', 'x_link', 'Bryły razem, bez scalania', plain=True, scroll=True)
        self.lk_action = ui.Segmented([('Połącz', 'join', 'lk_join'), ('Rozłącz', 'split', 'lk_split')], 34)
        self.lk_action.currentIndexChanged.connect(lambda *_: self._lk_reset())
        lay.addWidget(self.lk_action)
        lay.addWidget(ui.StepRow(1, 'x_object', 'Wskaż bryły', plain=True))
        self.lk_status = _label('', 'status')
        self.lk_status.setWordWrap(True)
        lay.addWidget(self.lk_status)
        self.lk_help = _label('', 'help')
        self.lk_help.setWordWrap(True)
        lay.addWidget(self.lk_help)
        self.lk_apply, close = self._buttons(self.link_panel.footer, 'Zatwierdź', 'Zamknij', self.apply_link, lambda: self.set_mode(None))
        close.setToolTip('Zamyka okno bez zmian.')
        self.lk_ids = []
        self._lk_hover = None

    # ---------- stan ----------
    def _link_enter(self):
        self.link_panel.show()
        self.lk_action.setCurrentIndex(0)
        self.lk_ids = []
        self._lk_hover = None
        self.view.setCursor(Qt.PointingHandCursor)
        self._lk_update()
        self.hint('Połącz: najedź na bryłę (podświetli się) i kliknij; prawy przycisk odznacza. Zatwierdź albo Enter.')

    def _link_leave(self):
        self.lk_ids = []
        self._lk_hover = None
        self.view.tints = {}
        self.view.set_preview_mesh(None)

    def _lk_reset(self):
        self.lk_ids = []
        self._lk_hover = None
        self.view.set_preview_mesh(None)
        self._lk_update()

    def _lk_joining(self):
        return self.lk_action.currentData() == 'join'

    def _lk_unit(self, bid):
        """Bryły wskazywane razem z klikniętą: przy łączeniu - jej grupa / wcześniejsze połączenie, przy rozłączaniu -
        całe połączenie (pusta lista, gdy bryła nie jest połączona)."""
        body = self.document.get(bid) if bid else None
        if body is None or body.kind != 'solid':
            return []
        if self._lk_joining():
            return [i for i in self._group_ids(bid) if (b := self.document.get(i)) is not None and b.kind == 'solid']
        link = hist.link_of(body)
        return [b.id for b in self.document.bodies if link and hist.link_of(b) == link]

    def _lk_update(self):
        if not hasattr(self, 'lk_status'):
            return
        live = {b.id for b in self.document.bodies}
        self.lk_ids = [i for i in self.lk_ids if i in live]
        self.view.tints = {i: LINK_TINT for i in self.lk_ids} if self.mode == 'link' else {}
        n = len(self.lk_ids)
        if self._lk_joining():
            self.lk_status.setText('Kliknij co najmniej dwie bryły (albo grupy na liście Obiekty).' if n == 0 else
                                   f'Wybrane bryły: {n}.' + (' Wskaż jeszcze co najmniej jedną.' if n < 2 else ' Zatwierdź łączy je w całość.'))
            self.lk_help.setText('Połączone bryły zaznaczają się, przesuwają i tną inne bryły razem, ale nie są scalone - '
                                 'widać miejsca styku. Na liście Obiekty trafią do jednej grupy. Prawy przycisk odznacza bryłę.')
            self.lk_apply.setEnabled(n >= 2)
        else:
            links = {hist.link_of(self.document.get(i)) for i in self.lk_ids} - {''}
            self.lk_status.setText('Kliknij jedną z połączonych brył - zaznaczy się całe połączenie.' if not links else
                                   f'Połączenia do rozłączenia: {len(links)} ({n} brył). Zatwierdź je rozłącza.')
            self.lk_help.setText('Po rozłączeniu bryły są znowu niezależne i wracają do swoich dawnych grup na liście Obiekty. '
                                 'Prawy przycisk odznacza.')
            self.lk_apply.setEnabled(bool(links))
        self.refresh()

    # ---------- mysz ----------
    def link_hover(self, x, y):
        bid = self.view.pick_body(x, y)
        ids = self._lk_unit(bid)
        key = tuple(ids) or None
        if key == self._lk_hover:
            return
        self._lk_hover = key
        meshes = [b.mesh for i in ids if (b := self.document.get(i)) is not None and b.mesh is not None]
        if not meshes:
            self.view.set_preview_mesh(None)
            return
        from .studio import _merge_meshes
        self.view.set_preview_mesh(_merge_meshes(meshes), color=(.98, .62, .2, .35), line_color=(.9, .45, .05, 1), width=2.4, on_top=True)

    def pick_link(self, x, y):
        bid = self.view.pick_body(x, y)
        ids = self._lk_unit(bid)
        if not ids:
            self.toast('Kliknij bryłę.' if self._lk_joining() else 'Kliknij bryłę, która jest połączona z innymi.')
            return
        self.lk_add(ids)

    def lk_add(self, ids, toggle=False):
        ids = [i for i in ids if (b := self.document.get(i)) is not None and b.kind == 'solid']
        if not self._lk_joining():
            ids = [j for i in ids for j in self._lk_unit(i)]
        if not ids:
            self.toast('Ta pozycja nie zawiera ' + ('brył.' if self._lk_joining() else 'połączonych brył.'))
            return
        if toggle and all(i in self.lk_ids for i in ids):
            self.lk_ids = [i for i in self.lk_ids if i not in ids]
        else:
            self.lk_ids = [*self.lk_ids, *[i for i in dict.fromkeys(ids) if i not in self.lk_ids]]
        self._lk_update()

    def unpick_link(self, x, y):
        """Prawy przycisk: odznacza wskazaną bryłę (razem z jej grupą / połączeniem)."""
        bid = self.view.pick_body(x, y)
        ids = self._lk_unit(bid)
        if not ids or not any(i in self.lk_ids for i in ids):
            return
        self.lk_ids = [i for i in self.lk_ids if i not in ids]
        self._lk_update()

    # ---------- zatwierdzenie ----------
    def apply_link(self):
        if self.busy:
            return
        doc = self.document
        ids = [i for i in self.lk_ids if doc.get(i) is not None]
        if self._lk_joining():
            if len(ids) < 2:
                self.toast('Wskaż co najmniej dwie bryły.')
                return
            # bryły z wcześniejszych połączeń wchodzą do nowego w całości
            old = {hist.link_of(doc.get(i)) for i in ids} - {''}
            ids += [b.id for b in doc.bodies if hist.link_of(b) in old and b.id not in ids]
            folder = hist.unique_folder([b for b in doc.bodies if b.id not in ids], 'Połączenie')
            recipe = dict(type='link', action='join', ids=ids, link=uuid.uuid4().hex, folder=folder)
            label = f'Połączenie: {len(ids)} brył'
        else:
            links = sorted({hist.link_of(doc.get(i)) for i in ids} - {''})
            if not links:
                self.toast('Kliknij połączoną bryłę.')
                return
            recipe = dict(type='link', action='split', links=links)
            label = 'Rozłączenie' + (f' ({len(links)})' if len(links) > 1 else '')
        try:
            bodies = hist.run_link(list(doc.bodies), recipe)
        except Exception as exc:
            self.toast(str(exc))
            return
        doc.pending_op = recipe
        doc.pending_label, doc.pending_icon = label, 'link'
        doc.commit(bodies)
        self.set_mode(None)
        self.selected = list(ids) if recipe['action'] == 'join' else []
        self.toast(f'{label} - zaznaczają się i przesuwają razem.' if recipe['action'] == 'join' else
                   'Rozłączono - bryły są znowu niezależne.', 3500)
        self.refresh()
