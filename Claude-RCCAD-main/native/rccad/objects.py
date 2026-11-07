"""Panel „Obiekty” po prawej stronie pola roboczego: lista szkiców, brył i tekstów z numerem kolejności dodania,
przyciskami ukrycia / wyłączenia / usunięcia oraz zaznaczaniem wielu pozycji (Shift / Ctrl)."""
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QScrollArea, QToolButton, QVBoxLayout, QWidget

from . import icons, shell_ui as ui

GROUPS = (('sketch', 'Szkice', 'sketch'), ('text', 'Teksty', 'text'), ('solid', 'Bryły', 'solid'))
WIDTH = 292

QSS = """
QFrame#objects { background:rgba(255,255,255,0.97); border:1px solid #b9cde0; border-radius:15px; }
QFrame#objects[strip="true"] { border-radius:11px; border-top-right-radius:0; border-bottom-right-radius:0; border-right:0; }
QFrame#objects QToolButton#stripbtn { color:#2f87e8; font-size:15px; font-weight:900; border-radius:9px; }
QFrame#objects QToolButton#stripbtn:hover { background:#e6f1fc; }
QFrame#objects QLabel { background:transparent; border:0; color:#29475e; }
QFrame#objects QLabel#title { font-size:13px; font-weight:700; color:#1d3a56; }
QFrame#objects QLabel#count { background:#e3f0fd; color:#1f6fc9; border-radius:9px; font-size:11px; font-weight:700; padding:1px 8px; }
QFrame#objects QLabel#group { font-size:11px; font-weight:700; color:#5b7a93; }
QFrame#objects QLabel#num { font-size:11px; font-weight:700; color:#2f87e8; }
QFrame#objects QLabel#empty { color:#7d93a6; font-size:12px; padding:18px 10px; }
QFrame#objects QToolButton { border:0; background:transparent; border-radius:6px; padding:0; }
QFrame#objects QToolButton:hover { background:#e6f1fc; }
QFrame#objects QToolButton#del:hover { background:#fde9e6; }
QFrame#objects QToolButton#fold { color:#5b7a93; font-weight:700; }
QFrame#objects QScrollArea { border:0; background:transparent; }
QFrame#objects QWidget#body { background:transparent; }
QFrame#objects QScrollBar:vertical { width:8px; background:transparent; margin:2px; }
QFrame#objects QScrollBar::handle:vertical { background:#c3d5e6; border-radius:3px; min-height:24px; }
QFrame#objects QScrollBar::add-line:vertical, QFrame#objects QScrollBar::sub-line:vertical { height:0; }
QFrame#objects QScrollBar:horizontal { height:8px; background:transparent; margin:2px; }
QFrame#objects QScrollBar::handle:horizontal { background:#c3d5e6; border-radius:3px; min-width:24px; }
QFrame#objects QScrollBar::add-line:horizontal, QFrame#objects QScrollBar::sub-line:horizontal { width:0; }
QWidget#orow { background:transparent; border-radius:9px; }
QWidget#orow:hover { background:#eef5fc; }
QWidget#orow[sel="true"] { background:#dcecff; border:1px solid #8ec0f3; }
QWidget#orow[off="true"] QLabel { color:#9aabba; }
QWidget#fhead { background:#f2f7fc; border-radius:8px; }
QWidget#fhead:hover { background:#e6f1fc; }
QFrame#objects QLabel#fname { font-size:12px; font-weight:700; color:#29475e; }
QFrame#objects QLabel#badge { background:#eef4fa; color:#5b7a93; border-radius:8px; font-size:10px; font-weight:700; padding:0 6px; }
"""


def category(body):
    if body.kind == 'solid':
        return 'solid'
    return 'text' if body.name.startswith('Tekst') else 'sketch'


def _icon(name, size=18):
    cache = _icon.__dict__.setdefault('cache', {})
    if (name, size) not in cache:
        cache[(name, size)] = QIcon(icons.pixmap('t_' + name, size))
    return cache[(name, size)]


class _NameEdit(QLineEdit):
    """Pole zmiany nazwy: Enter zatwierdza (sygnał returnPressed), Esc i utrata fokusu rezygnują."""
    cancelled = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.cancelled.emit()


class Row(QWidget):
    clicked = Signal(str, object)
    hovered = Signal(str)
    renamed = Signal(str, str)
    editing = Signal(bool)

    menu = Signal(str, object)            # id, pozycja globalna - menu kontekstowe (grupy)

    def __init__(self, oid, number, kind, icon, name, hidden, locked, selected, hooks, count=1, indent=0):
        super().__init__()
        self.oid = oid
        self.setObjectName('orow')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty('sel', bool(selected))
        self.setProperty('off', bool(hidden or locked))
        self.setFixedHeight(34)
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8 + indent, 3, 6, 3)
        lay.setSpacing(4)
        pic = QLabel()
        pic.setPixmap(icons.pixmap('t_' + icon, 20))
        pic.setFixedSize(22, 22)
        if hidden or locked:
            pic.setEnabled(False)
        num = QLabel(f'#{number}')
        num.setObjectName('num')
        num.setMinimumWidth(30)
        label = QLabel(name)
        label.setToolTip(name)
        label.setStyleSheet('font-size:12px;')
        self.label, self.name, self.edit = label, name, None
        self._lay = lay
        lay.addWidget(pic)
        lay.addWidget(num)
        lay.addWidget(label, 1)
        if count > 1:            # szyk „jako jeden element”: jedna pozycja z liczbą elementów
            badge = QLabel(f'×{count}')
            badge.setObjectName('badge')
            badge.setToolTip(f'Jeden element: {count} kształtów razem')
            lay.addWidget(badge)
        for key, icon_name, tip, active in (('hide', 'eyeoff' if hidden else 'eye', 'Pokaż' if hidden else 'Ukryj', hidden),
                                            ('lock', 'lock' if locked else 'unlock', 'Włącz (odblokuj)' if locked else 'Wyłącz (nie do zaznaczania)', locked),
                                            ('del', 'trash', 'Usuń', False)):
            b = QToolButton()
            b.setObjectName(key)
            b.setIcon(_icon(icon_name))
            b.setIconSize(QSize(18, 18))
            b.setFixedSize(26, 26)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key, o=oid: QTimer.singleShot(0, lambda: hooks[k](o)))
            lay.addWidget(b)

    def enterEvent(self, event):
        self.hovered.emit(self.oid)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit('')
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.edit is None:
            self.start_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def start_edit(self):
        self.edit = _NameEdit(self.name)
        self.edit.setStyleSheet('background:white;border:1px solid #2f87e8;border-radius:6px;padding:1px 4px;font-size:12px;')
        self.edit.setFixedHeight(24)
        self._lay.insertWidget(2, self.edit, 1)
        self.label.hide()
        self.editing.emit(True)
        self.edit.returnPressed.connect(self._commit)
        self.edit.cancelled.connect(self._cancel)
        self.edit.setFocus()
        self.edit.selectAll()

    def _commit(self):
        if self.edit is None:
            return
        text, oid = self.edit.text().strip(), self.oid
        self._close_edit()
        if text and text != self.name:
            QTimer.singleShot(0, lambda: self.renamed.emit(oid, text))

    def _cancel(self):
        if self.edit is not None:
            self._close_edit()

    def _close_edit(self):
        edit, self.edit = self.edit, None
        edit.blockSignals(True)
        self._lay.removeWidget(edit)
        edit.deleteLater()
        self.label.show()
        self.editing.emit(False)

    def contextMenuEvent(self, event):
        oid, where = self.oid, event.globalPos()
        QTimer.singleShot(0, lambda: self.menu.emit(oid, where))
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            oid, mods = self.oid, event.modifiers()
            QTimer.singleShot(0, lambda: self.clicked.emit(oid, mods))   # lista jest przebudowywana - nie wewnątrz własnego zdarzenia
            event.accept()
            return
        super().mousePressEvent(event)


class FolderHead(QWidget):
    """Nagłówek grupy (folderu) na liście: zwijanie, nazwa (dwuklik - zmiana), liczba, ukrycie i usunięcie całej grupy."""
    renamed = Signal(str, str)
    editing = Signal(bool)

    def __init__(self, name, count, folded, hidden, hooks):
        super().__init__()
        self.name, self.edit = name, None
        self.setObjectName('fhead')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(30)
        self.setCursor(Qt.PointingHandCursor)
        self.hooks = hooks
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 6, 2)
        lay.setSpacing(4)
        fold = QToolButton()
        fold.setObjectName('fold')
        fold.setText('▸' if folded else '▾')
        fold.setFixedSize(18, 18)
        fold.clicked.connect(lambda: QTimer.singleShot(0, hooks['fold']))
        pic = QLabel()
        pic.setPixmap(icons.pixmap('t_folder', 18))
        pic.setFixedSize(20, 20)
        self.label = QLabel(name)
        self.label.setObjectName('fname')
        self.label.setToolTip(f'Grupa „{name}” - dwuklik zmienia nazwę, prawy przycisk: rozgrupuj')
        badge = QLabel(str(count))
        badge.setObjectName('badge')
        self._lay = lay
        lay.addWidget(fold)
        lay.addWidget(pic)
        lay.addWidget(self.label, 1)
        lay.addWidget(badge)
        for key, icon_name, tip in (('hide', 'eyeoff' if hidden else 'eye', 'Pokaż grupę' if hidden else 'Ukryj grupę'),
                                    ('del', 'trash', 'Usuń całą grupę')):
            b = QToolButton()
            b.setObjectName(key)
            b.setIcon(_icon(icon_name, 16))
            b.setIconSize(QSize(16, 16))
            b.setFixedSize(24, 22)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: QTimer.singleShot(0, hooks[k]))
            lay.addWidget(b)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            QTimer.singleShot(0, self.hooks['select'])
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.edit is None:
            self.edit = _NameEdit(self.name)
            self.edit.setStyleSheet('background:white;border:1px solid #2f87e8;border-radius:6px;padding:1px 4px;font-size:12px;')
            self.edit.setFixedHeight(22)
            self._lay.insertWidget(2, self.edit, 1)
            self.label.hide()
            self.editing.emit(True)
            self.edit.returnPressed.connect(self._commit)
            self.edit.cancelled.connect(self._close)
            self.edit.setFocus()
            self.edit.selectAll()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _commit(self):
        if self.edit is None:
            return
        text, old = self.edit.text().strip(), self.name
        self._close()
        if text and text != old:
            QTimer.singleShot(0, lambda: self.renamed.emit(old, text))

    def _close(self):
        if self.edit is None:
            return
        edit, self.edit = self.edit, None
        edit.blockSignals(True)
        self._lay.removeWidget(edit)
        edit.deleteLater()
        self.label.show()
        self.editing.emit(False)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('Zmień nazwę grupy', lambda: self.mouseDoubleClickEvent(_FakeDouble()))
        menu.addAction('Rozgrupuj (zostaw elementy)', self.hooks['ungroup'])
        menu.exec(event.globalPos())
        event.accept()


class _FakeDouble:
    def button(self):
        return Qt.LeftButton

    def accept(self):
        pass


def units(items):
    """Pozycje listy: elementy jednej grupy szyku („jako jeden element”) łączą się w jedną pozycję.
    items: (id, kategoria, numer, nazwa, grupa, folder) -> (id, kategoria, numer, nazwa, liczba, folder, id członków)."""
    out, seen = [], {}
    for oid, cat, number, name, group, folder in items:
        key = (cat, group) if group else None
        if key is not None and key in seen:
            unit = seen[key]
            unit[4] += 1
            unit[6].append(oid)
            if number < unit[2]:                 # pozycję reprezentuje najstarszy element (oryginał szyku)
                unit[0], unit[2], unit[3] = oid, number, name
            continue
        unit = [oid, cat, number, name, 1, folder, [oid]]
        out.append(unit)
        if key is not None:
            seen[key] = unit
    for unit in out:
        if unit[4] > 1:
            unit[3] = unit[3].split(' — szyk')[0]
    return [tuple(u) for u in out]


class ObjectsPanel(QFrame):
    """Widok listy; stan (ukrycie, blokada, zaznaczenie) trzyma okno Studio, panel tylko go rysuje i zgłasza kliknięcia."""
    select = Signal(str, object)          # id, modyfikatory
    hide_toggled = Signal(str)
    lock_toggled = Signal(str)
    delete_requested = Signal(str)
    group_hide = Signal(str)
    group_delete = Signal(str)
    rename = Signal(str, str)             # id, nowa nazwa
    hover = Signal(str)                   # id obiektu pod kursorem listy ('' = żaden)
    folder_move = Signal(object, str)     # id pozycji, nazwa grupy ('' = wyjmij z grupy)
    folder_new = Signal(object)           # id pozycji -> nowa grupa
    folder_rename = Signal(str, str)      # stara, nowa nazwa
    folder_hide = Signal(object)          # id elementów grupy
    folder_delete = Signal(object)
    folder_select = Signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('objects')
        self.setStyleSheet(QSS)
        self.setFixedWidth(WIDTH)
        self._sig = None
        self._folded = set()
        self._editing = False
        self._stale = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 8, 8)
        outer.setSpacing(6)
        self._outer = outer
        # zwinięte okno: cienki pasek przy prawej krawędzi ze strzałką na środku (klik rozwija)
        self.strip = QToolButton()
        self.strip.setObjectName('stripbtn')
        self.strip.setText('◂')
        self.strip.setToolTip('Rozwiń listę obiektów')
        self.strip.setCursor(Qt.PointingHandCursor)
        self.strip.setSizePolicy(self.strip.sizePolicy().horizontalPolicy(), self.strip.sizePolicy().verticalPolicy())
        self.strip.clicked.connect(self._toggle_collapse)
        self.strip.hide()
        outer.addWidget(self.strip)
        self.head_box = QWidget()
        head = QHBoxLayout(self.head_box)
        head.setContentsMargins(4, 0, 2, 0)
        pic = QLabel()
        pic.setPixmap(icons.pixmap('t_layers', 22))
        title = QLabel('Obiekty')
        title.setObjectName('title')
        self.count = QLabel('0')
        self.count.setObjectName('count')
        self.collapse = QToolButton()
        self.collapse.setText('▸')
        self.collapse.setObjectName('fold')
        self.collapse.setFixedSize(24, 24)
        self.collapse.setToolTip('Zwiń listę do paska przy prawej krawędzi')
        self.collapse.clicked.connect(self._toggle_collapse)
        head.addWidget(pic)
        head.addWidget(title)
        head.addWidget(self.count)
        head.addStretch(1)
        self.new_folder = QToolButton()
        self.new_folder.setIcon(_icon('folderadd', 20))
        self.new_folder.setIconSize(QSize(20, 20))
        self.new_folder.setFixedSize(26, 26)
        self.new_folder.setToolTip('Nowa grupa z zaznaczonych elementów (prawy przycisk na elemencie - przenieś do grupy)')
        self.new_folder.setCursor(Qt.PointingHandCursor)
        self.new_folder.clicked.connect(lambda: QTimer.singleShot(0, lambda: self.folder_new.emit(None)))
        head.addWidget(self.new_folder)
        head.addWidget(self.collapse)
        outer.addWidget(self.head_box)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer.addWidget(self.scroll, 1)
        self.hint = QLabel('Shift / Ctrl + klik – wiele pozycji · dwuklik – zmiana nazwy · prawy przycisk – grupy · Delete – usuń zaznaczone')
        self.hint.setObjectName('small')
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet('font-size:10px;color:#7d93a6;padding:0 4px;')
        outer.addWidget(self.hint)
        self.rows = {}
        self.open = True
        ui.shadow(self, 22, 5, 44)

    # ------------------------------------------------------------------
    STRIP = 22

    def _toggle_collapse(self):
        """Zwinięcie: okno chowa się w cienki pasek przy prawej krawędzi (strzałka na środku rozwija je z powrotem)."""
        self.open = not self.open
        for w in (self.head_box, self.scroll, self.hint):
            w.setVisible(self.open)
        self.strip.setVisible(not self.open)
        self.setProperty('strip', not self.open)
        self.style().unpolish(self)
        self.style().polish(self)
        if self.open:
            self._outer.setContentsMargins(10, 10, 8, 8)
            self.setFixedWidth(WIDTH)
        else:
            self._outer.setContentsMargins(2, 4, 2, 4)
            self.setFixedWidth(self.STRIP)
        self.relayout()
        window = self.window()
        if hasattr(window, '_layout_overlays'):
            window._layout_overlays()

    def relayout(self):
        """Wysokość zależy od liczby pozycji, ale nie przekracza dostępnego miejsca (parent.height - 320)."""
        parent = self.parentWidget()
        room = max(120, (parent.height() if parent else 700) - 320)
        if not self.open:
            self.setFixedHeight(min(room, 150))
            self.strip.setFixedSize(self.STRIP - 4, min(room, 150) - 8)
            return
        content = self.scroll.widget().sizeHint().height() if self.scroll.widget() else 60
        self.setFixedHeight(int(min(room, max(110, content + 84 + (self.scroll.horizontalScrollBar().height() if self.scroll.horizontalScrollBar().isVisible() else 0)))))

    def update_items(self, items, selected, hidden, locked):
        """items: lista (id, kategoria, numer, nazwa, grupa szyku, folder)."""
        if self._editing:
            self._stale = (items, selected, hidden, locked)      # lista przebuduje się po zakończeniu edycji nazwy
            return
        items = [tuple(it) + ('', '')[len(it) - 4:] if len(it) < 6 else tuple(it) for it in items]
        sig = (tuple(items), tuple(selected), tuple(sorted(hidden)), tuple(sorted(locked)), tuple(sorted(self._folded)))
        if sig == self._sig:
            return
        self._sig = sig
        self._items = items
        rows = units(items)
        self._members = {u[0]: list(u[6]) for u in rows}
        self.count.setText(str(len(rows)))
        keep = self.scroll.verticalScrollBar().value()
        body = QWidget()
        body.setObjectName('body')
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 2, 0)
        lay.setSpacing(2)
        hooks = dict(hide=self.hide_toggled.emit, lock=self.lock_toggled.emit, **{'del': self.delete_requested.emit})
        self.rows = {}
        any_item = False

        def add_row(unit, indent):
            oid, cat, number, name, count, folder, members = unit
            icon = next(ic for c, _, ic in GROUPS if c == cat)
            row = Row(oid, number, cat, icon, name, all(m in hidden for m in members), all(m in locked for m in members),
                      oid in selected, hooks, count=count, indent=indent)
            row.clicked.connect(self.select.emit)
            row.hovered.connect(self.hover.emit)
            row.renamed.connect(self.rename.emit)
            row.editing.connect(self._set_editing)
            row.menu.connect(self._row_menu)
            self.rows[oid] = row
            lay.addWidget(row)

        for cat, title, icon in GROUPS:
            group = [u for u in rows if u[1] == cat]
            if not group:
                continue
            any_item = True
            head = QHBoxLayout()
            head.setContentsMargins(6, 6, 0, 2)
            fold = QToolButton()
            fold.setObjectName('fold')
            fold.setText('▸' if cat in self._folded else '▾')
            fold.setFixedSize(18, 18)
            fold.clicked.connect(lambda _=False, c=cat: QTimer.singleShot(0, lambda: self._fold(c)))
            label = QLabel(f'{title.upper()}  ·  {len(group)}')
            label.setObjectName('group')
            all_hidden = all(m in hidden for u in group for m in u[6])
            eye = QToolButton()
            eye.setIcon(_icon('eyeoff' if all_hidden else 'eye', 16))
            eye.setIconSize(QSize(16, 16))
            eye.setFixedSize(24, 22)
            eye.setToolTip('Pokaż całą grupę' if all_hidden else 'Ukryj całą grupę')
            eye.clicked.connect(lambda _=False, c=cat: QTimer.singleShot(0, lambda: self.group_hide.emit(c)))
            trash = QToolButton()
            trash.setObjectName('del')
            trash.setIcon(_icon('trash', 16))
            trash.setIconSize(QSize(16, 16))
            trash.setFixedSize(24, 22)
            trash.setToolTip('Usuń całą grupę')
            trash.setCursor(Qt.PointingHandCursor)
            trash.clicked.connect(lambda _=False, c=cat: QTimer.singleShot(0, lambda: self.group_delete.emit(c)))
            eye.setCursor(Qt.PointingHandCursor)
            head.addWidget(fold)
            head.addWidget(label, 1)
            head.addWidget(eye)
            head.addWidget(trash)
            lay.addLayout(head)
            if cat in self._folded:
                continue
            done_folders = set()
            for unit in group:
                folder = unit[5]
                if not folder:
                    add_row(unit, 0)
                    continue
                if folder in done_folders:
                    continue
                done_folders.add(folder)
                inside = [u for u in group if u[5] == folder]
                ids = [m for u in inside for m in u[6]]
                key = f'{cat}:{folder}'
                fh = FolderHead(folder, len(inside), key in self._folded, all(m in hidden for m in ids), dict(
                    fold=lambda k=key: self._fold(k),
                    hide=lambda ids=ids: self.folder_hide.emit(ids),
                    select=lambda ids=ids: self.folder_select.emit(ids),
                    ungroup=lambda ids=ids: self.folder_move.emit(ids, ''),
                    **{'del': lambda ids=ids: self.folder_delete.emit(ids)}))
                fh.renamed.connect(self.folder_rename.emit)
                fh.editing.connect(self._set_editing)
                lay.addWidget(fh)
                if key not in self._folded:
                    for u in inside:
                        add_row(u, 18)
        if not any_item:
            empty = QLabel('Pole robocze jest puste.\nNarysuj szkic albo dodaj bryłę.')
            empty.setObjectName('empty')
            empty.setAlignment(Qt.AlignCenter)
            lay.addWidget(empty)
        lay.addStretch(1)
        longest = max((self.fontMetrics().horizontalAdvance(u[3]) for u in rows), default=0)
        body.setMinimumWidth(longest + 196)      # dłuższe nazwy przewijają się w poziomie
        self.scroll.setWidget(body)
        self.scroll.verticalScrollBar().setValue(keep)
        self.relayout()

    def folders(self):
        return sorted({it[5] for it in getattr(self, '_items', ()) if it[5]})

    def _row_menu(self, oid, where):
        """Prawy przycisk na elemencie: przeniesienie do istniejącej grupy, nowa grupa, wyjęcie z grupy."""
        menu = QMenu(self)
        current = next((it[5] for it in getattr(self, '_items', ()) if it[0] == oid), '')
        move = menu.addMenu(_icon('folder', 16), 'Przenieś do grupy')
        others = [f for f in self.folders() if f != current]
        for name in others:
            move.addAction(_icon('folder', 16), name, lambda n=name: self.folder_move.emit([oid], n))
        if not others:
            move.setEnabled(False)
        menu.addAction(_icon('folderadd', 16), 'Nowa grupa…', lambda: self.folder_new.emit([oid]))
        if current:
            menu.addAction(f'Wyjmij z grupy „{current}”', lambda: self.folder_move.emit([oid], ''))
        menu.exec(where)

    def _set_editing(self, on):
        self._editing = on
        if not on and self._stale is not None:
            args, self._stale = self._stale, None
            QTimer.singleShot(0, lambda: self.update_items(*args))

    def _fold(self, cat):
        self._folded.symmetric_difference_update({cat})
        self._sig = None
        self.refill()

    def refill(self):
        """Wywoływane przez okno po zwinięciu grupy - ono przekazuje aktualne dane ponownie."""
        if self.parent() is not None and hasattr(self.window(), 'objects_update'):
            self.window().objects_update()
