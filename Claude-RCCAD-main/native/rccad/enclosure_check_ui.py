"""Kontrola obudowy (etap 12 Generatora obudów): panel wyników z trzema poziomami (Poprawne / Ostrzeżenie / Błąd),
kliknięcie wyniku podświetla obszar w widoku 3D i wskazuje element. Dostępna w oknie „Utwórz obudowę” (przed
zatwierdzeniem - na liczonej obudowie) i jako narzędzie „Kontrola obudowy” dla gotowych obudów w dokumencie (z
otworami i wentylacją). Liczenie w tle (run_preview), nic nie trafia do dokumentu. Logika: rccad.enclosure_check."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QListWidget, QListWidgetItem, QPushButton

from . import enclosure as enc
from . import enclosure_check as chk
from . import enclosure_param as epm
from . import kernel
from . import shell_ui as ui
from .enclosure_ui import _label

MARK = {'ok': '✔', 'warning': '⚠', 'error': '✖'}
COLOR = {'ok': '#1e8449', 'warning': '#b9770e', 'error': '#c0392b'}
WORD = {'ok': 'Poprawne', 'warning': 'Ostrzeżenie', 'error': 'Błąd'}
HILITE = ((1, .15, .15, .45), (.8, 0, 0, 1))


def results_with_meshes(results):
    """Wyniki z siatkami obszarów do podświetlenia (liczone w tle)."""
    import cadquery as cq
    out = []
    for lvl, text, shape, ref in results:
        mesh = None
        if shape is not None:
            try:
                mesh = kernel.display_mesh(cq.Shape.cast(shape))
            except Exception:
                mesh = None
        out.append((lvl, text, mesh, ref))
    return out


def check_document(bodies, enclosure_id):
    """Kontrola gotowej obudowy w dokumencie: wszystkie jej części (podstawa / pokrywa albo jedna bryła) z otworami i
    wentylacją, mocowania, zamknięcia i ruch odtworzone z definicji (meta 'enclosure')."""
    by_id = {b.id: b for b in bodies}
    body = by_id.get(enclosure_id)
    if body is None or not (body.meta or {}).get('enclosure'):
        raise kernel.CadError('Wskaż obudowę z Generatora obudów.')
    spec = enc.EnclosureSpec.from_json(body.meta['enclosure'])
    group = [b for b in bodies if (b.meta or {}).get('enclosure') and (b.id == body.id or (body.folder and b.folder == body.folder
                                                                                          and (b.meta or {}).get('enclosure_part')))]
    parts, part_of, holes, vents = {}, {}, [], []
    for b in group:
        name = (b.meta or {}).get('enclosure_part') or 'body'
        if b.kind != 'solid' or name.startswith(('flat_', 'bends_', 'pin')):
            continue                                        # rozkroje, linie gięcia i kołki - nie części obudowy
        parts[name] = b.shape.wrapped
        part_of[b.id] = name
        holes += list((b.meta or {}).get('enclosure_holes', []))
        vents += list((b.meta or {}).get('enclosure_vents', []))
    data = chk.gather(bodies, spec, parts, holes, vents, part_of)
    return chk.run(parts, **data)


def check_spec(bodies, spec):
    """Kontrola obudowy liczonej w oknie (przed zatwierdzeniem)."""
    env = enc.envelope(bodies, spec)
    spec.envelope = env
    built, _t, _i = enc.build_parts(env, spec, bodies, check_sources=False)
    parts = {k: v.wrapped for k, v in built.items()}
    data = chk.gather(bodies, spec, parts)
    return chk.run(parts, **data)


class EnclosureCheckTools:
    def _check_widgets(self, lay, key):
        """Lista wyników kontroli (wspólna dla okna obudowy i narzędzia „Kontrola obudowy”)."""
        listw = QListWidget()
        listw.setObjectName('enclist')
        listw.setMinimumHeight(150)
        listw.setWordWrap(True)
        listw.setStyleSheet('QListWidget#enclist { background:#ffffff; border:1px solid #d6e0ea; border-radius:8px; padding:2px; outline:0; }'
                            ' QListWidget#enclist::item { padding:4px 6px; border-radius:6px; }'
                            ' QListWidget#enclist::item:selected { background:#fde2e2; color:#17314a; }')
        listw.currentRowChanged.connect(lambda row, k=key: self._check_pick(k, row))
        self._check_lists = getattr(self, '_check_lists', {})
        self._check_lists[key] = listw
        lay.addWidget(listw)
        summary = _label('', 'value')
        lay.addWidget(summary)
        return listw, summary

    def _check_show(self, key, results, listw, summary):
        self._check_results = getattr(self, '_check_results', {})
        self._check_results[key] = results
        listw.blockSignals(True)
        listw.clear()
        order = {'error': 0, 'warning': 1, 'ok': 2}
        for lvl, text, mesh, ref in sorted(results, key=lambda r: order[r[0]]):
            item = QListWidgetItem(f'{MARK[lvl]} {WORD[lvl]}: {text}')
            item.setForeground(QColor(COLOR[lvl]))
            item.setData(Qt.UserRole, results.index((lvl, text, mesh, ref)))
            item.setToolTip('Kliknij - podświetl obszar w widoku' if (mesh is not None or ref) else '')
            listw.addItem(item)
        listw.blockSignals(False)
        e, w = sum(1 for r in results if r[0] == 'error'), sum(1 for r in results if r[0] == 'warning')
        summary.setText(f'Błędy: {e} · ostrzeżenia: {w} · poprawne: {len(results) - e - w}')
        summary.setStyleSheet(f'font-weight:700; color:{COLOR["error" if e else ("warning" if w else "ok")]};')

    def _check_pick(self, key, row):
        """Klik w wynik: podświetlenie obszaru kolizji / elementu w widoku."""
        listw = self._check_lists[key]
        item = listw.item(row) if row >= 0 else None
        if item is None:
            return
        lvl, text, mesh, ref = self._check_results[key][item.data(Qt.UserRole)]
        meshes = []
        if mesh is not None:
            meshes.append((mesh, *HILITE))
        body = self.document.get(ref) if ref else None
        if body is not None and body.mesh is not None:
            meshes.append((body.mesh, (1, .7, .2, .25), (.95, .45, .02, 1)))
        self.view.set_selection_meshes(meshes)
        if meshes:
            self.toast(text)

    # ------------------------------------------------------------------ w oknie „Utwórz obudowę”
    def _build_enc_check(self, lay):
        self.enc_step8 = ui.StepRow(8, 'x_enccheck', 'Kontrola obudowy', plain=True)
        lay.addWidget(self.enc_step8)
        button = QPushButton('Sprawdź obudowę')
        button.setToolTip('Kolizje, odstępy, grubości, poprawność brył, montaż i otwieranie - przed zatwierdzeniem')
        button.clicked.connect(lambda _=False: self.enc_run_check())
        lay.addWidget(button)
        self.enc_chk_list, self.enc_chk_sum = self._check_widgets(lay, 'enc')

    def enc_run_check(self):
        if self.enc.get('layout') is None or self.enc.get('split_error'):
            self.toast(self.enc.get('error') or 'Najpierw ustaw poprawną obudowę.')
            return
        spec = self.enc_spec()
        bodies = list(self.document.bodies)
        self.enc_chk_sum.setText('Kontrola w toku…')

        def compute():
            return results_with_meshes(check_spec(bodies, spec))

        def show(value, error):
            if self.mode != 'enclosure':
                return
            if error or value is None:
                value = [('error', f'Kontrola nie powiodła się: {error}', None, None)]
            self._check_show('enc', value, self.enc_chk_list, self.enc_chk_sum)
            e = sum(1 for r in value if r[0] == 'error')
            self.enc_step8.set_state('done' if not e else 'active', 'bez błędów' if not e else f'{e} błąd(y)')
        self.run_preview('enccheck', compute, show)

    # ------------------------------------------------------------------ narzędzie „Kontrola obudowy”
    def _build_enccheck_panel(self):
        self.chk_panel, lay = self._panel(320, 'Kontrola obudowy', 'x_enccheck', 'Kliknij obudowę', plain=True, scroll=True)
        self.chk_status = _label('Kliknij obudowę (albo jej podstawę / pokrywę) z Generatora obudów.', 'status')
        lay.addWidget(self.chk_status)
        again = QPushButton('Sprawdź ponownie')
        again.clicked.connect(lambda _=False: self.enccheck_run())
        lay.addWidget(again)
        self.chk_list, self.chk_sum = self._check_widgets(lay, 'tool')
        # --- etap 13: obudowa parametryczna ---
        self.chk_step = ui.StepRow(2, 'x_enclosure', 'Obudowa parametryczna', plain=True)
        lay.addWidget(self.chk_step)
        self.chk_state = _label('', 'value')
        lay.addWidget(self.chk_state)
        self.chk_mode = QComboBox()
        for key in epm.MODES:
            self.chk_mode.addItem(epm.MODE_LABELS[key], key)
        self.chk_mode.setToolTip('Automatyczna - przebudowa po zmianie elementów; ręczna - przycisk Aktualizuj; zamrożona - bez zmian i edycji')
        self.chk_mode.currentIndexChanged.connect(lambda *_: self.enc_set_mode(self.chk_mode.currentData()))
        lay.addWidget(self.chk_mode)
        self.chk_regen = QPushButton('Aktualizuj teraz')
        self.chk_regen.clicked.connect(lambda _=False: self.enc_regenerate(self.chk_target))
        lay.addWidget(self.chk_regen)
        self.chk_edit = QPushButton('Edytuj parametry obudowy')
        self.chk_edit.clicked.connect(lambda _=False: self.chk_target and self.edit_enclosure(self.chk_target))
        lay.addWidget(self.chk_edit)
        lay.addWidget(_label('Operacje składowe (dwuklik - edycja):', 'label'))
        self.chk_ops = QListWidget()
        self.chk_ops.setObjectName('enclist')
        self.chk_ops.setFixedHeight(110)
        self.chk_ops.setStyleSheet(self.chk_list.styleSheet())
        self.chk_ops.itemDoubleClicked.connect(lambda item: self.history_edit(item.data(Qt.UserRole)))
        lay.addWidget(self.chk_ops)
        self.chk_convert = QPushButton('Konwertuj do niezależnych brył')
        self.chk_convert.setToolTip('Usuwa parametry generatora - zostają zwykłe bryły B-Rep (Cofnij przywraca)')
        self.chk_convert.clicked.connect(lambda _=False: self.enc_convert(self.chk_target))
        lay.addWidget(self.chk_convert)
        self._build_enc_export(lay)                   # etap 15: zestawienie, masa i eksport
        self._buttons(self.chk_panel.footer, 'Zamknij', 'Anuluj', lambda: self.set_mode(None), lambda: self.set_mode(None))
        return self.chk_panel

    # ------------------------------------------------------------------ etap 13: stan, tryb, aktualizacja, konwersja
    def _enc_ops(self, body_id):
        """Kroki historii tej obudowy: definicja, otwory, wentylacja, aktualizacje, tryby."""
        body = self.document.get(body_id)
        if body is None:
            return []
        ids = {b.id for b in epm.group(self.document.bodies, body)}
        out = []
        for index, (_b, info) in enumerate(self.document.states()):
            op = info.get('op') or {}
            t = op.get('type')
            if (t == 'enclosure' and ids & {op.get('out'), op.get('out_lid')}) or (t in ('enc_hole', 'enc_vent') and op.get('target') in ids) \
                    or (t in ('enc_regen', 'enc_mode', 'enc_convert') and op.get('id') in ids):
                out.append((index, info.get('label') or t))
        return out

    def _chk_state_update(self):
        body = self.document.get(getattr(self, 'chk_target', None) or '')
        on = body is not None and bool((body.meta or {}).get('enclosure'))
        for w_ in (self.chk_mode, self.chk_regen, self.chk_edit, self.chk_convert, self.chk_ops):
            w_.setEnabled(on)
        self.chk_ops.clear()
        if hasattr(self, 'chk_export'):
            self._chk_summary_update()
        if not on:
            self.chk_state.setText('')
            return
        mode = (body.meta or {}).get('enclosure_mode', 'auto')
        self.chk_mode.blockSignals(True)
        self.chk_mode.setCurrentIndex(self.chk_mode.findData(mode))
        self.chk_mode.blockSignals(False)
        failed = getattr(self, '_enc_failed', {}).get(body.id)
        old = epm.stale(self.document.bodies, body)
        if failed:
            text, color = f'Wymaga aktualizacji - ostatnia przebudowa nie powiodła się: {failed}', '#c0392b'
        elif old:
            text, color = 'Wymaga aktualizacji - elementy źródłowe zmieniły się.', '#b9770e'
        else:
            text, color = 'Aktualna.', '#1e8449'
        self.chk_state.setText(text)
        self.chk_state.setStyleSheet(f'font-weight:700; color:{color};')
        self.chk_regen.setEnabled(mode != 'frozen')
        self.chk_edit.setEnabled(mode != 'frozen')
        for index, label in self._enc_ops(body.id):
            item = QListWidgetItem(f'Krok {index}: {label}')
            item.setData(Qt.UserRole, index)
            self.chk_ops.addItem(item)

    def enc_set_mode(self, mode):
        body = self.document.get(getattr(self, 'chk_target', None) or '')
        if body is None or (body.meta or {}).get('enclosure_mode', 'auto') == mode or self.busy:
            return
        recipe = dict(type='enc_mode', id=body.id, mode=mode)
        bodies = epm.set_mode(self.document.bodies, recipe)
        self.document.pending_op = recipe
        self.document.pending_label = 'Tryb obudowy'
        self.document.pending_icon = 'enclosure'
        self.document.commit(bodies)
        self.refresh()
        self._chk_state_update()

    def enc_convert(self, body_id):
        body = self.document.get(body_id or '')
        if body is None or self.busy:
            return
        recipe = dict(type='enc_convert', id=body.id)
        bodies = epm.convert(self.document.bodies, recipe)
        self.document.pending_op = recipe
        self.document.pending_label = 'Konwersja obudowy do brył'
        self.document.pending_icon = 'enclosure'
        self.document.commit(bodies)
        self.toast('Obudowa zamieniona na niezależne bryły B-Rep (Cofnij przywraca parametry).', 5000)
        self.refresh()
        self._chk_state_update()

    def enc_regenerate(self, body_id, auto=False):
        """Przebudowa obudowy w tle; błąd - zostaje ostatnia poprawna geometria i oznaczenie „wymaga aktualizacji”."""
        body = self.document.get(body_id or '')
        if body is None or self.busy:
            return
        recipe = dict(type='enc_regen', id=body.id)
        bodies = list(self.document.bodies)
        revision = id(self.document.bodies)
        self._enc_failed = getattr(self, '_enc_failed', {})

        def compute():
            return epm.regenerate(bodies, recipe)

        def show(value, error):
            if id(self.document.bodies) != revision:
                return                                         # dokument zmienił się w trakcie - nieaktualny wynik
            if error or value is None:
                self._enc_failed[body.id] = str(error)
                self.toast(f'{body.folder or body.name}: aktualizacja nie powiodła się ({error}). Zostaje ostatnia poprawna geometria.', 8000)
            else:
                self._enc_failed.pop(body.id, None)
                self.document.pending_op = recipe
                self.document.pending_label = 'Aktualizacja obudowy'
                self.document.pending_icon = 'enclosure'
                self.document.commit(value)
                self.refresh()
                if auto:
                    self.toast(f'{body.folder or body.name}: przebudowana po zmianie elementów (Cofnij - bez aktualizacji).', 4000)
            if self.mode == 'enccheck':
                self._chk_state_update()
        self.run_preview('encregen', compute, show)

    def enc_watch(self):
        """Po zmianie dokumentu: obudowy, których elementy się zmieniły - tryb automatyczny przebudowuje, ręczny oznacza."""
        if self.busy or self.mode is not None:
            return
        self._enc_tried = getattr(self, '_enc_tried', set())
        seen = set()
        for b in self.document.bodies:
            meta = b.meta or {}
            if b.kind != 'solid' or not meta.get('enclosure') or not meta.get('enclosure_sig'):
                continue
            key0 = b.folder if meta.get('enclosure_part') else b.id
            if key0 in seen:
                continue
            seen.add(key0)
            mode = meta.get('enclosure_mode', 'auto')
            if mode == 'frozen' or not epm.stale(self.document.bodies, b):
                continue
            key = (b.id, tuple(id(x.shape) for x in self.document.bodies if x.id in meta['enclosure_sig']))
            if key in self._enc_tried:
                continue
            self._enc_tried.add(key)
            if mode == 'auto':
                self.enc_regenerate(b.id, auto=True)
                return
            self.toast(f'{b.folder or b.name}: elementy się zmieniły - obudowa wymaga aktualizacji (Kontrola obudowy → Aktualizuj teraz).', 6000)

    def _enccheck_begin(self):
        self.chk_target = None
        self.chk_panel.show()
        self.chk_list.clear()
        self.chk_sum.setText('')
        sel = [i for i in self.selected if (self.document.get(i).meta or {}).get('enclosure')] if self.selected else []
        if sel:
            self.chk_target = sel[0]
            self.enccheck_run()
        else:
            self._chk_state_update()
        self.view.setCursor(Qt.PointingHandCursor)

    def enccheck_hover(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        self.view.set_hover_mesh(body.mesh if body is not None and (body.meta or {}).get('enclosure') else None)

    def enccheck_click(self, x, y, shift=False):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or not (body.meta or {}).get('enclosure'):
            self.toast('Kliknij obudowę z Generatora obudów.')
            return
        self.chk_target = body.id
        self.enccheck_run()

    def enccheck_run(self):
        self._chk_state_update()
        if not getattr(self, 'chk_target', None):
            return
        bodies, target = list(self.document.bodies), self.chk_target
        self.chk_status.setText(f'Kontrola: {self.document.get(target).name}…')

        def compute():
            return results_with_meshes(check_document(bodies, target))

        def show(value, error):
            if self.mode != 'enccheck':
                return
            if error or value is None:
                value = [('error', f'Kontrola nie powiodła się: {error}', None, None)]
            self.chk_status.setText(f'Obudowa: {self.document.get(target).name if self.document.get(target) else "—"}')
            self._check_show('tool', value, self.chk_list, self.chk_sum)
        self.run_preview('enccheck', compute, show)
