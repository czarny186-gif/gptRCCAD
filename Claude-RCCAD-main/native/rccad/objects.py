"""Panel „Obiekty” po prawej stronie pola roboczego: lista szkiców, brył i tekstów z numerem kolejności dodania,
przyciskami ukrycia / wyłączenia / usunięcia oraz zaznaczaniem wielu pozycji (Shift / Ctrl)."""
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QToolButton, QVBoxLayout, QWidget

from . import icons, shell_ui as ui

GROUPS = (('sketch', 'Szkice', 'sketch'), ('text', 'Teksty', 'text'), ('solid', 'Bryły', 'solid'))
WIDTH = 252

QSS = """
QFrame#objects { background:rgba(255,255,255,0.97); border:1px solid #b9cde0; border-radius:15px; }
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

    def __init__(self, oid, number, kind, icon, name, hidden, locked, selected, hooks):
        super().__init__()
        self.oid = oid
        self.setObjectName('orow')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty('sel', bool(selected))
        self.setProperty('off', bool(hidden or locked))
        self.setFixedHeight(34)
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 3, 6, 3)
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

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            oid, mods = self.oid, event.modifiers()
            QTimer.singleShot(0, lambda: self.clicked.emit(oid, mods))   # lista jest przebudowywana - nie wewnątrz własnego zdarzenia
            event.accept()
            return
        super().mousePressEvent(event)


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
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 2, 0)
        pic = QLabel()
        pic.setPixmap(icons.pixmap('t_layers', 22))
        title = QLabel('Obiekty')
        title.setObjectName('title')
        self.count = QLabel('0')
        self.count.setObjectName('count')
        self.collapse = QToolButton()
        self.collapse.setText('▾')
        self.collapse.setObjectName('fold')
        self.collapse.setFixedSize(24, 24)
        self.collapse.setToolTip('Zwiń / rozwiń listę')
        self.collapse.clicked.connect(self._toggle_collapse)
        head.addWidget(pic)
        head.addWidget(title)
        head.addWidget(self.count)
        head.addStretch(1)
        head.addWidget(self.collapse)
        outer.addLayout(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer.addWidget(self.scroll, 1)
        self.hint = QLabel('Shift / Ctrl + klik – wiele pozycji · dwuklik – zmiana nazwy · Delete – usuń zaznaczone')
        self.hint.setObjectName('small')
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet('font-size:10px;color:#7d93a6;padding:0 4px;')
        outer.addWidget(self.hint)
        self.rows = {}
        self.open = True
        ui.shadow(self, 22, 5, 44)

    # ------------------------------------------------------------------
    def _toggle_collapse(self):
        self.open = not self.open
        self.collapse.setText('▾' if self.open else '▸')
        self.scroll.setVisible(self.open)
        self.hint.setVisible(self.open)
        self.relayout()

    def relayout(self):
        """Wysokość zależy od liczby pozycji, ale nie przekracza dostępnego miejsca (parent.height - 320)."""
        parent = self.parentWidget()
        room = max(120, (parent.height() if parent else 700) - 320)
        if not self.open:
            self.setFixedHeight(46)
            return
        content = self.scroll.widget().sizeHint().height() if self.scroll.widget() else 60
        self.setFixedHeight(int(min(room, max(110, content + 84 + (self.scroll.horizontalScrollBar().height() if self.scroll.horizontalScrollBar().isVisible() else 0)))))

    def update_items(self, items, selected, hidden, locked):
        """items: lista (id, kategoria, numer, nazwa)."""
        if self._editing:
            self._stale = (items, selected, hidden, locked)      # lista przebuduje się po zakończeniu edycji nazwy
            return
        sig = (tuple(items), tuple(selected), tuple(sorted(hidden)), tuple(sorted(locked)), tuple(sorted(self._folded)))
        if sig == self._sig:
            return
        self._sig = sig
        self.count.setText(str(len(items)))
        keep = self.scroll.verticalScrollBar().value()
        body = QWidget()
        body.setObjectName('body')
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 2, 0)
        lay.setSpacing(2)
        hooks = dict(hide=self.hide_toggled.emit, lock=self.lock_toggled.emit, **{'del': self.delete_requested.emit})
        self.rows = {}
        any_item = False
        for cat, title, icon in GROUPS:
            group = [it for it in items if it[1] == cat]
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
            all_hidden = all(it[0] in hidden for it in group)
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
            for oid, _, number, name in group:
                row = Row(oid, number, cat, icon, name, oid in hidden, oid in locked, oid in selected, hooks)
                row.clicked.connect(self.select.emit)
                row.hovered.connect(self.hover.emit)
                row.renamed.connect(self.rename.emit)
                row.editing.connect(self._set_editing)
                self.rows[oid] = row
                lay.addWidget(row)
        if not any_item:
            empty = QLabel('Pole robocze jest puste.\nNarysuj szkic albo dodaj bryłę.')
            empty.setObjectName('empty')
            empty.setAlignment(Qt.AlignCenter)
            lay.addWidget(empty)
        lay.addStretch(1)
        longest = max((self.fontMetrics().horizontalAdvance(it[3]) for it in items), default=0)
        body.setMinimumWidth(longest + 190)      # dłuższe nazwy przewijają się w poziomie
        self.scroll.setWidget(body)
        self.scroll.verticalScrollBar().setValue(keep)
        self.relayout()

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
